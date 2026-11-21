"""Private Loon subscription cleaner and persistent node registry.

Sub-Store owns both parsing and final Loon serialization. This service owns
selection, durable identifiers and snapshots; it never interprets proxy URI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
import zlib
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, time as time_only
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import (
    REGIONS, endpoint_key, filter_reason, node_fingerprint, normalize_name,
    region_for, safe_label, valid_proxy, valid_upstream_url,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("loon-cleaner")
DB_PATH = os.environ.get("DB_PATH", "/data/registry.sqlite3")
SUBSTORE_API = os.environ.get("SUBSTORE_API", "http://sub-store:3000").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://example.invalid").rstrip("/")
FINGERPRINT_KEY = os.environ.get("FINGERPRINT_KEY", "")
SNAPSHOT_KEY = os.environ.get("SNAPSHOT_KEY", "")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))
FEED_TOKENS = {name: os.environ.get("FEED_TOKEN_" + name.upper(), "") for name in REGIONS}
SYNC_LOCK = asyncio.Lock()
CIPHER = None


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def now() -> int:
    return int(time.time())


def encode_snapshot(nodes: list[dict]) -> bytes:
    payload = json.dumps(nodes, separators=(",", ":"), ensure_ascii=False).encode()
    return CIPHER.encrypt(zlib.compress(payload, 6))


def decode_snapshot(raw: bytes | None) -> list[dict]:
    if not raw:
        return []
    return json.loads(zlib.decompress(CIPHER.decrypt(raw)))


def init_db():
    global CIPHER
    if not FINGERPRINT_KEY or len(FINGERPRINT_KEY) < 48:
        raise RuntimeError("FINGERPRINT_KEY must be a persistent high-entropy secret")
    if any(len(token) < 40 for token in FEED_TOKENS.values()):
        raise RuntimeError("Each FEED_TOKEN must be a persistent high-entropy token")
    CIPHER = Fernet(SNAPSHOT_KEY.encode())
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sub_name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                last_success INTEGER,
                last_error TEXT,
                node_count INTEGER NOT NULL DEFAULT 0,
                snapshot BLOB
            );
            CREATE TABLE IF NOT EXISTS nodes (
                source_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                norm_name TEXT NOT NULL,
                manual_alias TEXT,
                endpoint TEXT NOT NULL,
                server TEXT,
                port TEXT,
                protocol TEXT,
                status TEXT NOT NULL DEFAULT 'auto',
                region_override TEXT,
                review_reason TEXT,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (source_id, fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_node_status ON nodes(status,active);
            CREATE INDEX IF NOT EXISTS idx_node_name ON nodes(source_id,norm_name);
            CREATE TABLE IF NOT EXISTS global_exclusions (
                fingerprint TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                pattern TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feeds (
                region TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                count INTEGER NOT NULL,
                warning TEXT NOT NULL DEFAULT '',
                published_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scheduler (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


async def substore(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    async with httpx.AsyncClient(timeout=httpx.Timeout(110.0, connect=15.0), trust_env=False) as client:
        resp = await client.request(method, SUBSTORE_API + path, json=payload, params=params)
        resp.raise_for_status()
        return resp


async def substore_json(method: str, path: str, payload: dict | None = None):
    resp = await substore(method, path, payload)
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError("Sub-Store rejected the operation")
    return data.get("data")


async def ensure_output_subscription(name: str, content: str, existing: set[str]):
    payload = {"name": name, "source": "local", "content": content, "process": [], "noFlow": True}
    if name in existing:
        await substore_json("PATCH", "/api/sub/" + quote(name, safe=""), payload)
    else:
        await substore_json("POST", "/api/subs", payload)
        existing.add(name)


def ingest_source(db: sqlite3.Connection, source: sqlite3.Row, proxies: list[dict]):
    stamp = now()
    db.execute("UPDATE nodes SET active=0 WHERE source_id=?", (source["id"],))
    for proxy in proxies:
        if not valid_proxy(proxy):
            continue
        fp = node_fingerprint(proxy, FINGERPRINT_KEY)
        raw_name = proxy["name"]
        normalized = normalize_name(raw_name)
        endpoint = endpoint_key(proxy)
        current = db.execute(
            "SELECT status FROM nodes WHERE source_id=? AND fingerprint=?",
            (source["id"], fp),
        ).fetchone()
        if current:
            db.execute("""
                UPDATE nodes SET last_name=?, norm_name=?, endpoint=?, server=?,
                    port=?, protocol=?, last_seen=?, active=1
                WHERE source_id=? AND fingerprint=?
            """, (raw_name, normalized, endpoint, str(proxy.get("server", "")),
                  str(proxy.get("port", "")), str(proxy.get("type", "")),
                  stamp, source["id"], fp))
            continue
        old = db.execute("""
            SELECT * FROM nodes WHERE source_id=? AND fingerprint<>?
              AND (norm_name=? OR endpoint=?)
            ORDER BY last_seen DESC LIMIT 20
        """, (source["id"], fp, normalized, endpoint)).fetchall()
        exact = [row for row in old if row["norm_name"] == normalized and row["endpoint"] == endpoint]
        previously_excluded = [row for row in old if row["status"] == "exclude"]
        alias, override = None, None
        if len(exact) == 1:
            previous = exact[0]
            # A credential rotation may change the fingerprint without
            # changing the airport's specific slot. Carry explicit decisions.
            status = previous["status"] if previous["status"] in {"keep", "exclude"} else "auto"
            reason = "matched_existing_name_and_endpoint" if status == "exclude" else None
            alias, override = previous["manual_alias"], previous["region_override"]
        elif previously_excluded:
            status, reason = "review", "possibly_replaced_excluded_node"
        else:
            status, reason = "auto", None
        db.execute("""
            INSERT INTO nodes (source_id,fingerprint,first_name,last_name,norm_name,
                manual_alias,endpoint,server,port,protocol,status,region_override,
                review_reason,first_seen,last_seen,active)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """, (source["id"], fp, raw_name, raw_name, normalized, alias, endpoint,
              str(proxy.get("server", "")), str(proxy.get("port", "")),
              str(proxy.get("type", "")), status, override, reason, stamp, stamp))


def render_plan(db: sqlite3.Connection):
    sources = db.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY created_at,id").fetchall()
    rules = [dict(x) for x in db.execute("SELECT * FROM rules WHERE enabled=1 ORDER BY id")]
    exclusions = {r["fingerprint"] for r in db.execute("SELECT fingerprint FROM global_exclusions")}
    buckets = {key: [] for key in REGIONS}
    duplicates = 0
    skipped = 0
    rejected = 0
    seen = set()
    for source in sources:
        for proxy in decode_snapshot(source["snapshot"]):
            if not valid_proxy(proxy):
                skipped += 1
                continue
            fp = node_fingerprint(proxy, FINGERPRINT_KEY)
            record_row = db.execute(
                "SELECT * FROM nodes WHERE source_id=? AND fingerprint=?",
                (source["id"], fp),
            ).fetchone()
            if not record_row:
                skipped += 1
                continue
            record = dict(record_row)
            reason = filter_reason(record, fp in exclusions, rules)
            if reason:
                rejected += 1
                continue
            if fp in seen:
                duplicates += 1
                continue
            seen.add(fp)
            final_proxy = {k: v for k, v in proxy.items() if not k.startswith("_")}
            display = safe_label(record["manual_alias"] or record["first_name"])
            bucket = region_for(record["last_name"], record["region_override"])
            # Loon receives one aggregate subscription. Stable server-side
            # prefixes let its lightweight local filters build regional groups.
            region_tag = {"hk": "HK - ", "us": "US - ", "jp": "JP - "}.get(bucket, "OTHER - ")
            final_proxy["name"] = region_tag + safe_label(source["name"])[:30] + " | " + display
            buckets["overseas"].append(final_proxy)
            if bucket:
                buckets[bucket].append(final_proxy)
    # Loon names must be unique even when source/name is duplicated.
    for bucket in buckets.values():
        name_used = set()
        for proxy in bucket:
            original = proxy["name"]
            label = original
            suffix = 2
            while label in name_used:
                label = safe_label(f"{original} #{suffix}")
                suffix += 1
            proxy["name"] = label
            name_used.add(label)
    return buckets, {"duplicates": duplicates, "rejected": rejected, "unsupported": skipped}


async def publish_cached_locked():
    with connect() as db:
        buckets, stats = render_plan(db)
    existing_data = await substore_json("GET", "/api/subs")
    existing = {x["name"] for x in existing_data or []}
    staged = {}
    for region, proxies in buckets.items():
        if not proxies:
            staged[region] = ("# No eligible nodes for this group\n", 0, "")
            continue
        key = "clean_" + region
        # Each line is a Clash-compatible single-node JSON record, which is
        # accepted by Sub-Store's Clash_All parser. It retains transport options.
        content = "\n".join(json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in proxies)
        await ensure_output_subscription(key, content, existing)
        response = await substore("GET", "/download/" + key + "/Loon", params={"noFlow": "true"})
        output = response.text.strip()
        entries = [line for line in output.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not entries or any("=" not in line for line in entries):
            raise RuntimeError("Invalid Loon output for " + region)
        if len(entries) > len(proxies):
            raise RuntimeError("Unexpected extra Loon entries for " + region)
        warning = "" if len(entries) == len(proxies) else (
            f"Sub-Store omitted {len(proxies) - len(entries)} unsupported/invalid nodes"
        )
        staged[region] = (output + "\n", len(entries), warning)
    # Keep the previous four published feeds intact if any earlier step fails.
    with connect() as db:
        for region, (text, count, warning) in staged.items():
            db.execute("""
                INSERT INTO feeds(region,content,count,warning,published_at)
                VALUES(?,?,?,?,?) ON CONFLICT(region) DO UPDATE SET
                content=excluded.content,count=excluded.count,
                warning=excluded.warning,published_at=excluded.published_at
            """, (region, CIPHER.encrypt(text.encode()), count, warning, now()))
    return {"feeds": {r: v[1] for r, v in staged.items()}, **stats}


async def publish_cached():
    if SYNC_LOCK.locked():
        raise HTTPException(409, "A refresh/publish task is already running")
    async with SYNC_LOCK:
        return await publish_cached_locked()


async def refresh_all(source_filter: str | None = None):
    if SYNC_LOCK.locked():
        raise HTTPException(409, "A refresh/publish task is already running")
    async with SYNC_LOCK:
        with connect() as db:
            query = "SELECT * FROM sources WHERE enabled=1"
            params = ()
            if source_filter:
                query += " AND id=?"
                params = (source_filter,)
            sources = db.execute(query + " ORDER BY created_at,id", params).fetchall()
        errors = []
        good = []
        for source in sources:
            try:
                response = await substore("GET", "/download/" + quote(source["sub_name"], safe="") + "/JSON",
                                          params={"noCache": "true", "noFlow": "true"})
                nodes = response.json()
                if not isinstance(nodes, list) or len(nodes) == 0:
                    raise ValueError("Empty/invalid subscription response")
                if len(nodes) > 10000:
                    raise ValueError("Subscription has too many nodes")
                recognized = [p for p in nodes if valid_proxy(p)]
                if not recognized:
                    raise ValueError("No Loon-compatible nodes found")
                with connect() as db:
                    ingest_source(db, source, recognized)
                    db.execute("""
                        UPDATE sources SET snapshot=?,last_success=?,last_error=NULL,node_count=? WHERE id=?
                    """, (encode_snapshot(recognized), now(), len(recognized), source["id"]))
                good.append({"source": source["name"], "count": len(recognized), "skipped": len(nodes)-len(recognized)})
            except Exception as exc:
                # Never log URLs or proxy credentials in errors.
                msg = "Subscription fetch/parse failed (" + type(exc).__name__ + ")"
                LOG.warning("Source refresh failed: id=%s type=%s", source["id"], type(exc).__name__)
                with connect() as db:
                    db.execute("UPDATE sources SET last_error=? WHERE id=?", (msg, source["id"]))
                errors.append({"source": source["name"], "error": msg})
        try:
            result = await publish_cached_locked()
        except Exception as exc:
            LOG.exception("Publishing failed")
            raise HTTPException(502, "Publishing failed; last published feeds were preserved") from exc
        return {"updated": good, "failed": errors, **result}


async def daily_task():
    while True:
        await asyncio.sleep(60)
        local = datetime.now(TZ)
        if local.time() < time_only(hour=5, minute=0):
            continue
        today = local.date().isoformat()
        with connect() as db:
            previous = db.execute("SELECT value FROM scheduler WHERE key='daily_run'").fetchone()
            source_count = db.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]
        if source_count == 0 or (previous and previous[0] == today) or SYNC_LOCK.locked():
            continue
        try:
            await refresh_all()
        except Exception:
            LOG.exception("Scheduled daily refresh failed; cached feeds remain available")
        finally:
            with connect() as db:
                db.execute("INSERT INTO scheduler(key,value) VALUES('daily_run',?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (today,))


@asynccontextmanager
async def lifespan(_app):
    init_db()
    task = asyncio.create_task(daily_task())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Loon VPS Cleaner", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=10, max_length=4096)
    ua: str = Field(default="", max_length=256)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, min_length=10, max_length=4096)
    ua: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


class NodeUpdate(BaseModel):
    status: str | None = None
    manual_alias: str | None = Field(default=None, max_length=100)
    region_override: str | None = None
    global_exclude: bool | None = None


class RuleCreate(BaseModel):
    source_id: str | None = None
    pattern: str = Field(min_length=1, max_length=256)


@app.get("/manager/", response_class=HTMLResponse)
async def manager():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def status():
    with connect() as db:
        src = db.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]
        records = [dict(x) for x in db.execute("""
            SELECT n.* FROM nodes n JOIN sources s ON n.source_id=s.id
            WHERE n.active=1 AND s.enabled=1
        """)]
        global_excluded = {x[0] for x in db.execute("SELECT fingerprint FROM global_exclusions")}
        rules = [dict(x) for x in db.execute("SELECT * FROM rules WHERE enabled=1")]
        feeds = [dict(r) for r in db.execute("SELECT region,count,warning,published_at FROM feeds ORDER BY region")]
    exc = sum(1 for n in records if filter_reason(n, n["fingerprint"] in global_excluded, rules)
              not in (None, "needs_review"))
    review = sum(1 for n in records if filter_reason(n, n["fingerprint"] in global_excluded, rules)
                 == "needs_review")
    return {"sources": src, "nodes": len(records), "excluded": exc, "review": review,
            "feeds": feeds, "syncing": SYNC_LOCK.locked(), "daily_at": "05:00 Asia/Shanghai"}


@app.get("/api/feeds")
async def feeds():
    with connect() as db:
        feed_meta = {r["region"]: dict(r) for r in db.execute(
            "SELECT region,count,warning,published_at FROM feeds")}
    return {"all": {
        "url": f"{PUBLIC_BASE_URL}/loon/all/{FEED_TOKENS['overseas']}",
        **feed_meta.get("overseas", {"count": 0, "warning": "Not published yet", "published_at": None})
    }}


@app.get("/loon/{region}/{token}")
async def loon_feed(region: str, token: str):
    # Do not reveal whether a group exists to unauthenticated callers.
    # /loon/all is the only URL users need. Keep legacy regional URLs working
    # for old Loon profiles, but do not advertise them in the manager UI.
    storage_region = "overseas" if region == "all" else region
    token_region = "overseas" if region == "all" else region
    if token_region not in REGIONS or not secrets.compare_digest(token, FEED_TOKENS[token_region]):
        raise HTTPException(404, "Not found")
    with connect() as db:
        row = db.execute("SELECT content FROM feeds WHERE region=?", (storage_region,)).fetchone()
    if not row:
        raise HTTPException(503, "No published subscription yet")
    content = CIPHER.decrypt(row["content"]).decode()
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/sources")
async def sources():
    with connect() as db:
        return [dict(r) for r in db.execute("""
            SELECT id,name,enabled,created_at,last_success,last_error,node_count
            FROM sources ORDER BY created_at,id
        """)]


@app.post("/api/sources")
async def create_source(data: SourceCreate):
    try:
        url = valid_upstream_url(data.url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    source_id = uuid.uuid4().hex[:16]
    sub_name = "source_" + source_id
    payload = {"name": sub_name, "source": "remote", "url": url,
               "ua": data.ua or "clash.meta/v1.19.23", "process": [], "noFlow": True}
    try:
        await substore_json("POST", "/api/subs", payload)
    except Exception as exc:
        raise HTTPException(502, "Cannot register subscription in Sub-Store") from exc
    try:
        with connect() as db:
            db.execute("INSERT INTO sources (id,name,sub_name,created_at) VALUES (?,?,?,?)",
                       (source_id, data.name.strip(), sub_name, now()))
    except Exception:
        # Avoid leaving an orphan upstream subscription on DB failure.
        try:
            await substore("DELETE", "/api/sub/" + sub_name)
        except Exception:
            pass
        raise
    return {"id": source_id, "name": data.name.strip(), "message": "Added; refresh to import nodes"}


@app.patch("/api/sources/{source_id}")
async def update_source(source_id: str, data: SourceUpdate):
    with connect() as db:
        source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        raise HTTPException(404, "Source not found")
    patch = {}
    if data.url is not None:
        try:
            patch["url"] = valid_upstream_url(data.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if data.ua is not None:
        patch["ua"] = data.ua or "clash.meta/v1.19.23"
    if patch:
        try:
            await substore_json("PATCH", "/api/sub/" + source["sub_name"], patch)
        except Exception as exc:
            raise HTTPException(502, "Cannot update Sub-Store subscription") from exc
    with connect() as db:
        db.execute("UPDATE sources SET name=?,enabled=? WHERE id=?", (
            data.name.strip() if data.name is not None else source["name"],
            int(data.enabled) if data.enabled is not None else source["enabled"], source_id))
    try:
        publish = await publish_cached()
    except Exception as exc:
        raise HTTPException(502, "Source updated, but publishing failed; previous feeds remain") from exc
    return {"ok": True, "publish": publish}


@app.post("/api/sync")
async def sync():
    return await refresh_all()


@app.post("/api/sources/{source_id}/sync")
async def sync_one(source_id: str):
    with connect() as db:
        if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
            raise HTTPException(404, "Source not found")
    return await refresh_all(source_id)


@app.post("/api/publish")
async def publish():
    return await publish_cached()


@app.get("/api/nodes")
async def list_nodes(q: str = "", status_filter: str = "", source_id: str = "", page: int = 1,
                     page_size: int = 80, include_missing: bool = False):
    page = min(max(1, page), 100000)
    page_size = min(max(1, page_size), 200)
    conds = [] if include_missing else ["n.active=1"]
    args = []
    if q:
        conds.append("(n.first_name LIKE ? OR n.last_name LIKE ? OR n.server LIKE ?)")
        args.extend(["%" + q[:100] + "%"] * 3)
    if source_id:
        conds.append("n.source_id=?")
        args.append(source_id)
    if status_filter in {"exclude", "review", "keep", "auto"}:
        conds.append("n.status=?")
        args.append(status_filter)
    where = " WHERE " + " AND ".join(conds) if conds else ""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM nodes n" + where, args).fetchone()[0]
        rows = db.execute("""
            SELECT n.*, s.name AS source_name,
             CASE WHEN g.fingerprint IS NULL THEN 0 ELSE 1 END AS global_excluded
            FROM nodes n JOIN sources s ON s.id=n.source_id
            LEFT JOIN global_exclusions g ON g.fingerprint=n.fingerprint
        """ + where + " ORDER BY s.created_at,n.first_seen LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size]).fetchall()
        rules = [dict(r) for r in db.execute("SELECT * FROM rules WHERE enabled=1")]
    result = []
    for row in rows:
        n = dict(row)
        n["effective_reason"] = filter_reason(n, bool(n["global_excluded"]), rules)
        n["effective_region"] = region_for(n["last_name"], n["region_override"]) or "overseas"
        result.append(n)
    return {"total": total, "page": page, "page_size": page_size, "nodes": result}


@app.put("/api/nodes/{source_id}/{fingerprint}")
async def edit_node(source_id: str, fingerprint: str, update: NodeUpdate):
    if update.status is not None and update.status not in {"auto", "keep", "exclude", "review"}:
        raise HTTPException(400, "Invalid node status")
    if update.region_override is not None and update.region_override not in {*REGIONS, "auto"}:
        raise HTTPException(400, "Invalid region")
    with connect() as db:
        row = db.execute("SELECT * FROM nodes WHERE source_id=? AND fingerprint=?",
                         (source_id, fingerprint)).fetchone()
        if not row:
            raise HTTPException(404, "Node not found")
        if update.status is not None:
            db.execute("UPDATE nodes SET status=?,review_reason=NULL WHERE source_id=? AND fingerprint=?",
                       (update.status, source_id, fingerprint))
        if update.manual_alias is not None:
            db.execute("UPDATE nodes SET manual_alias=? WHERE source_id=? AND fingerprint=?",
                       (safe_label(update.manual_alias) if update.manual_alias.strip() else None,
                        source_id, fingerprint))
        if update.region_override is not None:
            db.execute("UPDATE nodes SET region_override=? WHERE source_id=? AND fingerprint=?",
                       (None if update.region_override == "auto" else update.region_override,
                        source_id, fingerprint))
        if update.global_exclude is True:
            db.execute("INSERT OR IGNORE INTO global_exclusions(fingerprint,created_at) VALUES (?,?)",
                       (fingerprint, now()))
        elif update.global_exclude is False:
            db.execute("DELETE FROM global_exclusions WHERE fingerprint=?", (fingerprint,))
    try:
        feeds = await publish_cached()
    except Exception as exc:
        raise HTTPException(502, "Decision saved, publishing failed; old feeds remain") from exc
    return {"saved": True, "publish": feeds}


@app.get("/api/rules")
async def list_rules():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM rules ORDER BY id DESC")]


@app.post("/api/rules")
async def create_rule(data: RuleCreate):
    try:
        re.compile(data.pattern)
    except re.error as exc:
        raise HTTPException(400, "Invalid regular expression") from exc
    with connect() as db:
        if data.source_id and not db.execute("SELECT 1 FROM sources WHERE id=?", (data.source_id,)).fetchone():
            raise HTTPException(400, "Invalid source")
        db.execute("INSERT INTO rules(source_id,pattern,created_at) VALUES(?,?,?)",
                   (data.source_id, data.pattern, now()))
    try:
        await publish_cached()
    except Exception as exc:
        raise HTTPException(502, "Rule saved, publishing failed") from exc
    return {"saved": True}


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int):
    with connect() as db:
        db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    try:
        await publish_cached()
    except Exception as exc:
        raise HTTPException(502, "Rule deleted, publishing failed") from exc
    return {"saved": True}

class BatchNodeAction(BaseModel):
    nodes: list[dict[str, str]] = Field(min_length=1, max_length=1000)
    status: str


@app.post("/api/nodes/batch")
async def edit_nodes_batch(data: BatchNodeAction):
    if data.status not in {"auto", "keep", "exclude"}:
        raise HTTPException(400, "Invalid status")
    updated = 0
    with connect() as db:
        for item in data.nodes:
            src, fp = item.get("source_id", ""), item.get("fingerprint", "")
            if not re.fullmatch(r"[a-f0-9]{16}", src) or not re.fullmatch(r"[a-f0-9]{64}", fp):
                raise HTTPException(400, "Invalid source/node identifier")
            cursor = db.execute(
                "UPDATE nodes SET status=?,review_reason=NULL WHERE source_id=? AND fingerprint=?",
                (data.status, src, fp),
            )
            updated += cursor.rowcount
    try:
        result = await publish_cached()
    except Exception as exc:
        raise HTTPException(502, "Batch changes saved, publishing failed") from exc
    return {"updated": updated, "publish": result}


@app.middleware("http")
async def check_admin_origin(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != PUBLIC_BASE_URL:
            return PlainTextResponse("Cross-origin admin request rejected", status_code=403)
    return await call_next(request)

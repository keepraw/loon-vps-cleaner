import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeSubStore:
    def __init__(self):
        self.subs = {}
        self.data = {}
        self.fail_source = set()
        self.fail_publish = False

    async def api(self, method, path, payload=None):
        if method == "POST" and path == "/api/subs":
            if payload["name"] in self.subs:
                raise RuntimeError("duplicate")
            self.subs[payload["name"]] = payload.copy()
            return payload
        if method == "GET" and path == "/api/subs":
            return list(self.subs.values())
        if method == "PATCH" and path.startswith("/api/sub/"):
            name = path.split("/")[-1]
            self.subs[name].update(payload)
            return self.subs[name]
        raise AssertionError((method, path))

    async def request(self, method, path, payload=None, params=None):
        if method == "GET" and path.endswith("/JSON"):
            name = path.split("/")[2]
            if name in self.fail_source:
                raise httpx.ConnectError("synthetic failure")
            return httpx.Response(200, json=self.data[name])
        if method == "GET" and path.endswith("/Loon"):
            if self.fail_publish:
                raise RuntimeError("Synthetic publisher failure")
            name = path.split("/")[2]
            proxies = [json.loads(line) for line in self.subs[name]["content"].splitlines()]
            assert all("type" in n for n in proxies)
            output = "\n".join(
                f"{p['name']}=shadowsocks,{p['server']},{p['port']},{p['cipher']},\"{p['password']}\""
                for p in proxies
            )
            return httpx.Response(200, text=output)
        if method == "DELETE":
            self.subs.pop(path.split("/")[-1], None)
            return httpx.Response(200, json={"status": "success"})
        raise AssertionError((method, path))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINGERPRINT_KEY", "K" * 64)
    monkeypatch.setenv("SNAPSHOT_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    for region in ("HK", "US", "JP", "OVERSEAS"):
        monkeypatch.setenv("FEED_TOKEN_" + region, region + "-" + "X" * 48)
    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    fake = FakeSubStore()
    monkeypatch.setattr(module, "substore_json", fake.api)
    monkeypatch.setattr(module, "substore", fake.request)
    with TestClient(module.app) as c:
        yield c, module, fake


def node(name, server, password="p"):
    return {"name": name, "type": "ss", "server": server, "port": 443,
            "cipher": "aes-128-gcm", "password": password}


def test_full_import_exclude_rename_and_preserve_on_failure(client):
    c, module, fake = client
    create = c.post("/api/sources", json={"name":"Airport A", "url":"https://provider.example.com/get?token=test"})
    assert create.status_code == 200, create.text
    src = create.json()["id"]
    subname = "source_" + src
    fake.data[subname] = [node("HK Fast", "hk.example.com"), node("US Fast", "us.example.com"),
                          node("Tokyo JP", "jp.example.com"), node("Taiwan", "tw.example.com")]
    refresh = c.post("/api/sync")
    assert refresh.status_code == 200, refresh.text
    result = refresh.json()
    assert result["feeds"] == {"hk":1,"us":1,"jp":1,"overseas":4}
    assert "HK Fast" in c.get("/loon/hk/HK-"+"X"*48).text
    assert c.get("/loon/hk/not-a-valid-token").status_code == 404
    nodes = c.get("/api/nodes").json()["nodes"]
    hk = next(n for n in nodes if n["first_name"]=="HK Fast")
    change = c.put(f"/api/nodes/{src}/{hk['fingerprint']}", json={"status":"exclude"})
    assert change.status_code == 200, change.text
    assert c.get("/api/status").json()["feeds"][0]["count"] == 0
    assert "HK Fast" not in c.get("/loon/overseas/OVERSEAS-"+"X"*48).text
    # Renaming upstream must not bypass the stored exclusion.
    fake.data[subname][0]["name"] = "HK New Title"
    assert c.post("/api/sync").status_code == 200
    new_hk = next(n for n in c.get("/api/nodes").json()["nodes"] if n["first_name"]=="HK Fast")
    assert new_hk["status"] == "exclude"
    assert new_hk["last_name"] == "HK New Title"
    # A fetch failure must retain the previous successful snapshot and feeds.
    fake.fail_source.add(subname)
    fail = c.post("/api/sync")
    assert fail.status_code == 200
    assert len(fail.json()["failed"]) == 1
    assert c.get("/api/status").json()["feeds"][0]["count"] == 0


def test_quarantine_after_endpoint_and_credential_changed(client):
    c,module,fake=client
    src=c.post("/api/sources",json={"name":"A","url":"https://provider.example.net/sub"}).json()["id"]
    key="source_"+src
    fake.data[key]=[node("US 1","us.a.example","p1")]
    assert c.post("/api/sync").status_code==200
    target=c.get("/api/nodes").json()["nodes"][0]
    c.put(f"/api/nodes/{src}/{target['fingerprint']}",json={"status":"exclude"})
    fake.data[key]=[node("US 1","us.b.example","p2")]
    assert c.post("/api/sync").status_code==200
    entries=c.get("/api/nodes").json()["nodes"]
    assert len(entries)==1 and entries[0]["status"]=="review"
    assert c.get("/api/feeds").json()["all"]["count"]==0


def test_regex_rule_and_batch_restore(client):
    c,module,fake=client
    src=c.post("/api/sources",json={"name":"B","url":"https://provider.example.net/sub"}).json()["id"]
    fake.data["source_"+src]=[node("US Traffic 0.1x","us.a.example"),node("JP Good","jp.a.example")]
    assert c.post("/api/sync").status_code==200
    rule=c.post("/api/rules",json={"pattern":"Traffic","source_id":src})
    assert rule.status_code==200
    assert c.get("/api/feeds").json()["all"]["count"]==1
    target=next(n for n in c.get("/api/nodes").json()["nodes"] if "Traffic" in n["last_name"])
    result=c.post("/api/nodes/batch",json={"status":"keep","nodes":[{"source_id":src,"fingerprint":target["fingerprint"]}]})
    assert result.status_code==200, result.text
    assert c.get("/api/feeds").json()["all"]["count"]==2


def test_credential_rotation_same_slot_inherits_exclusion(client):
    c,module,fake=client
    src=c.post("/api/sources",json={"name":"C","url":"https://provider.example.net/sub"}).json()["id"]
    key="source_"+src
    fake.data[key]=[node("HK 01","hk.example.net",password="one")]
    assert c.post("/api/sync").status_code==200
    first=c.get("/api/nodes").json()["nodes"][0]
    assert c.put(f"/api/nodes/{src}/{first['fingerprint']}",json={"status":"exclude"}).status_code==200
    fake.data[key]=[node("HK 01","hk.example.net",password="two")]
    assert c.post("/api/sync").status_code==200
    current=c.get("/api/nodes").json()["nodes"]
    assert len(current)==1
    assert current[0]["fingerprint"] != first["fingerprint"]
    assert current[0]["status"]=="exclude"
    assert c.get("/api/feeds").json()["all"]["count"]==0


def test_publisher_failure_does_not_replace_cached_feeds(client):
    c,module,fake=client
    src=c.post("/api/sources",json={"name":"D","url":"https://provider.example.net/sub"}).json()["id"]
    key="source_"+src
    fake.data[key]=[node("HK A","hk.example.net")]
    assert c.post("/api/sync").status_code==200
    token="HK-"+"X"*48
    original=c.get("/loon/hk/"+token).text
    fake.data[key]=[node("HK B","hk2.example.net")]
    fake.fail_publish=True
    failed=c.post("/api/sync")
    assert failed.status_code==502
    assert c.get("/loon/hk/"+token).text==original
    fake.fail_publish=False
    assert c.post("/api/publish").status_code==200
    assert "HK B" in c.get("/loon/hk/"+token).text


def test_two_airports_duplicate_node_deduped_globally(client):
    c,module,fake=client
    a=c.post("/api/sources",json={"name":"A","url":"https://a.example.net/sub"}).json()["id"]
    b=c.post("/api/sources",json={"name":"B","url":"https://b.example.net/sub"}).json()["id"]
    duplicate=node("US Fast","shared.example.net")
    fake.data["source_"+a]=[duplicate]
    fake.data["source_"+b]=[{**duplicate,"name":"Different name"}]
    result=c.post("/api/sync")
    assert result.status_code==200, result.text
    assert result.json()["duplicates"]==1
    assert result.json()["feeds"]["overseas"]==1


def test_single_aggregated_loom_feed_and_server_region_tags(client):
    c, module, fake = client
    src = c.post("/api/sources", json={"name": "Airport A", "url": "https://provider.example.com/sub"}).json()["id"]
    fake.data["source_" + src] = [
        node("Hong Kong 01", "hk.example.com"),
        node("United States 01", "us.example.com"),
        node("Tokyo JP 01", "jp.example.com"),
        node("Taiwan 01", "tw.example.com"),
    ]
    result = c.post("/api/sync")
    assert result.status_code == 200, result.text
    feeds = c.get("/api/feeds").json()
    assert set(feeds) == {"all"}
    assert feeds["all"]["count"] == 4
    token = "OVERSEAS-" + "X" * 48
    output = c.get("/loon/all/" + token)
    assert output.status_code == 200
    assert "HK - Airport A | Hong Kong 01" in output.text
    assert "US - Airport A | United States 01" in output.text
    assert "JP - Airport A | Tokyo JP 01" in output.text
    assert "OTHER - Airport A | Taiwan 01" in output.text
    assert c.get("/loon/all/invalid").status_code == 404
    # The old overseas URL remains compatible with already-imported profiles.
    assert c.get("/loon/overseas/" + token).text == output.text

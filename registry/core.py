"""Pure node identity, classification and filtering logic."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import unicodedata
from urllib.parse import urlsplit

REGIONS = ("hk", "us", "jp", "overseas")
SUPPORTED_TYPES = frozenset({
    "ss", "ssr", "snell", "trojan", "vmess", "vless", "http",
    "socks5", "wireguard", "tailscale", "hysteria2", "anytls",
})

# Ignore cosmetic/runtime fields, while retaining every other connection setting.
IGNORED_FIELDS = frozenset({
    "name", "_subName", "_subDisplayName", "_collectionName",
    "_collectionDisplayName", "test-url", "test-timeout", "benchmark-url",
    "benchmark-timeout", "_IP", "_IPv4", "_IPv6", "_domain",
    "_resolved_ips", "resolved", "udp", "tfo", "block-quic",
    "_last_check", "flowInfo", "subscription-userinfo",
})

REGION_PATTERNS = {
    "hk": re.compile(r"(?:\U0001f1ed\U0001f1f0|\u9999\u6e2f|(?<![A-Za-z])HK(?:G)?(?=\d|\b)|hong\s*kong)", re.I),
    "us": re.compile(r"(?:\U0001f1fa\U0001f1f8|\u7f8e\u56fd|\u7f8e\u570b|(?<![A-Za-z])US(?:A)?(?=\d|\b)|united\s+states|america)", re.I),
    "jp": re.compile(r"(?:\U0001f1ef\U0001f1f5|\u65e5\u672c|(?<![A-Za-z])JP(?:N)?(?=\d|\b)|japan|tokyo|osaka)", re.I),
}


def canonical(value):
    """Normalize connection data without retaining display-only metadata."""
    if isinstance(value, dict):
        return {
            str(k): canonical(v)
            for k, v in sorted(value.items())
            if str(k) not in IGNORED_FIELDS and not str(k).startswith("_")
            and v is not None
        }
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def node_fingerprint(proxy: dict, secret: str) -> str:
    if not secret:
        raise ValueError("Fingerprint key must not be empty")
    obj = canonical(proxy)
    # Normalize hostname casing and trailing dot, but never mutate the source node.
    if isinstance(obj.get("server"), str):
        obj["server"] = obj["server"].strip().lower().rstrip(".")
    if obj.get("port") is not None:
        obj["port"] = str(obj["port"])
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name or "").strip()).casefold()


def endpoint_key(proxy: dict) -> str:
    return "|".join((
        str(proxy.get("type", "")).lower(),
        str(proxy.get("server", "")).strip().lower().rstrip("."),
        str(proxy.get("port", "")),
    ))


def region_for(name: str, override: str | None = None) -> str | None:
    if override in ("hk", "us", "jp"):
        return override
    if override == "overseas":
        return None
    for region in ("hk", "us", "jp"):
        if REGION_PATTERNS[region].search(name or ""):
            return region
    return None


def safe_label(name: str) -> str:
    name = re.sub(r"[=,\r\n\x00-\x1f]", " ", str(name or "Node"))
    return re.sub(r"\s+", " ", name).strip()[:100] or "Node"


def valid_upstream_url(url: str) -> str:
    url = str(url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("A public HTTPS subscription URL is required")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".local", ".localhost", ".internal", ".lan")
    ):
        raise ValueError("Local/private subscription hosts are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("Private, loopback and reserved IPs are not allowed")
    if len(url) > 4096:
        raise ValueError("Subscription URL is too long")
    if parts.fragment:
        raise ValueError("URL fragments are not supported; use a plain HTTPS link")
    return url


def filter_reason(record: dict, global_excluded: bool, regex_rules: list[dict]) -> str | None:
    if global_excluded:
        return "global_excluded"
    status = record.get("status", "auto")
    if status == "exclude":
        return "manually_excluded"
    if status == "review":
        return "needs_review"
    if status == "keep":
        return None
    name = record.get("last_name", "")
    for rule in regex_rules:
        if not rule.get("enabled", True):
            continue
        if rule.get("source_id") not in (None, record.get("source_id")):
            continue
        if re.search(rule["pattern"], name, re.I):
            return f"regex:{rule['id']}"
    return None


def valid_proxy(proxy: dict) -> bool:
    if not isinstance(proxy, dict) or proxy.get("type") not in SUPPORTED_TYPES:
        return False
    if not isinstance(proxy.get("name"), str) or not proxy["name"].strip():
        return False
    if proxy["type"] == "tailscale":
        return True
    if proxy["type"] == "wireguard":
        return bool(proxy.get("peers") or proxy.get("server"))
    try:
        port = int(proxy.get("port"))
    except (ValueError, TypeError):
        return False
    return bool(proxy.get("server")) and 1 <= port <= 65535

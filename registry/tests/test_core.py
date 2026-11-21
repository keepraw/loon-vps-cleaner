import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (endpoint_key, filter_reason, node_fingerprint, normalize_name,
                  region_for, safe_label, valid_proxy, valid_upstream_url)

SECRET = "abc123-" * 10


def example(name="HK Express", password="secret", server="hk.example.com"):
    return {"name": name, "type": "ss", "server": server, "port": 443,
            "cipher": "aes-128-gcm", "password": password, "udp": True,
            "_subName": "airport-a"}


def test_identity_survives_rename_metadata_and_ip_case():
    first = example()
    second = example("Hong Kong Express", server="HK.EXAMPLE.COM.")
    second["_subName"] = "airport-z"
    second["udp"] = False
    assert node_fingerprint(first, SECRET) == node_fingerprint(second, SECRET)


def test_identity_changes_when_password_server_or_transport_changes():
    p = example()
    assert node_fingerprint(p, SECRET) != node_fingerprint(example(password="other"), SECRET)
    assert node_fingerprint(p, SECRET) != node_fingerprint(example(server="other.example.com"), SECRET)
    p["plugin"] = "obfs"
    assert node_fingerprint(p, SECRET) != node_fingerprint(example(), SECRET)


def test_region_and_manual_override():
    assert region_for("Hong Kong HK premium") == "hk"
    assert region_for("HK01 IPLC") == "hk"
    assert region_for("US02 premium") == "us"
    assert region_for("JP-09") == "jp"
    assert region_for("PUSH server") is None
    assert region_for("US West California") == "us"
    assert region_for("Tokyo Japan") == "jp"
    assert region_for("Singapore") is None
    assert region_for("Los Angeles", "jp") == "jp"
    assert region_for("Hong Kong", "overseas") is None


def test_exclusion_priority():
    r = {"status": "keep", "source_id": "a", "last_name": "Traffic US"}
    rules = [{"id": 1, "source_id": None, "pattern": "traffic", "enabled": True}]
    assert filter_reason(r, False, rules) is None
    assert filter_reason(r, True, rules) == "global_excluded"
    r["status"] = "auto"
    assert filter_reason(r, False, rules) == "regex:1"
    r["status"] = "review"
    assert filter_reason(r, False, rules) == "needs_review"


def test_upstream_url_and_name_safety():
    assert valid_upstream_url("https://example.com/sub?token=foo")
    for url in ["http://example.com/sub", "https://127.0.0.1/sub",
                "https://localhost/sub", "https://192.168.0.10/sub",
                "https://user:pass@example.com/sub", "https://x.internal/sub"]:
        with pytest.raises(ValueError):
            valid_upstream_url(url)
    assert "\n" not in safe_label("node\nHK=admin,US")
    assert normalize_name("  Hong   Kong  ") == "hong kong"
    assert valid_proxy(example())
    assert not valid_proxy({"type": "tuic", "name": "unsupported"})

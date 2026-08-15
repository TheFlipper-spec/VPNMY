import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vpnmy.config import BuildConfig, Paths
from vpnmy.models import CheckResult, Source
from vpnmy.parser import parse_link
from vpnmy.publisher import atomic_publish, build_payloads, load_country_names


def test_payload(tmp_path, countries_file):
    s = Source("s", "S", "https://x", "universal")
    paths = Paths(
        tmp_path / "b64", tmp_path / "raw", tmp_path / "stats", tmp_path / "hist", countries_file
    )
    c = BuildConfig(
        (s,), paths, 1, 1, 10, 1, {"universal": 1}, ("DE",), 1, 1, 1, 5, 1, 5, 0, "xray"
    )
    n = parse_link(
        "vless://123e4567-e89b-12d3-a456-426614174000@1.1.1.1:443?encryption=none&security=tls&type=ws&sni=x.com",
        s,
    )
    r = CheckResult(
        n,
        20,
        50,
        10,
        "DE",
        "2026-01-01T00:00:00Z",
        90,
        resolved_ip="1.1.1.1",
        checks_passed=2,
    )
    p = build_payloads(
        [r],
        config=c,
        countries=load_country_names(countries_file),
        history={"schema_version": 1, "nodes": {}},
        source_stats=[],
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        check_mode="xray",
    )
    atomic_publish(p)
    assert (
        base64.b64decode(paths.subscription_base64.read_text()).decode()
        == paths.subscription_raw.read_text()
    )
    lines = paths.subscription_raw.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("vless://")
    stats = json.loads(paths.stats.read_text())
    assert stats["schema_version"] == 3
    assert stats["subscription_metadata_lines"] == 0
    assert stats["total"] == 1
    assert stats["servers"][0]["verified"] is True
    assert stats["servers"][0]["ip"] == "1.1.1.1"
    assert "🇩🇪 FL1P" in stats["servers"][0]["name"]


def test_atomic_publish_rolls_back_partial_replacement(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    real_replace = os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(target) == second and not failed:
            failed = True
            raise OSError("disk failure")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        atomic_publish({first: b"new first", second: b"new second"})

    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
    assert not list(tmp_path.glob(".*"))

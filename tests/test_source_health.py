import json

import pytest

from vpnmy.config import ConfigError
from vpnmy.models import Source
from vpnmy.source_health import (
    is_quarantined,
    load_health,
    prune_missing,
    record_run,
)
from vpnmy.sources import find_dead_sources, prune_dead_sources

S1 = Source("a", "A", "https://a.example/sub", "universal")
S2 = Source("b", "B", "https://b.example/sub", "universal")
NOW = "2026-09-15T10:00:00Z"


def run(health, source, ok=True, accepted=3, threshold=3, error=None, ts=NOW):
    return record_run(
        health,
        source,
        ok=ok,
        accepted=accepted,
        error=error,
        checked_at=ts,
        fail_threshold=threshold,
    )


def test_quarantine_and_recovery():
    health = {"schema_version": 1, "sources": {}}
    for _ in range(2):
        run(health, S1, ok=False, accepted=0, error="fetch_error")
    assert not is_quarantined(health, "a", 3)
    run(health, S1, ok=False, accepted=0, error="fetch_error")
    assert is_quarantined(health, "a", 3)
    assert health["sources"]["a"]["quarantined"] is True
    # первый успешный запуск выводит из карантина
    run(health, S1, ok=True, accepted=10)
    assert not is_quarantined(health, "a", 3)
    assert health["sources"]["a"]["fail_streak"] == 0


def test_empty_payload_counts_as_failure():
    health = {"schema_version": 1, "sources": {}}
    for _ in range(3):
        run(health, S1, ok=True, accepted=0, error=None)
    assert is_quarantined(health, "a", 3)
    assert health["sources"]["a"]["last_error"] == "empty"


def test_prune_missing_sources():
    health = {"schema_version": 1, "sources": {}}
    run(health, S1)
    run(health, S2)
    prune_missing(health, [S1])
    assert set(health["sources"]) == {"a"}


def test_load_corrupt_file(tmp_path):
    path = tmp_path / "health.json"
    path.write_text("{ broken")
    health = load_health(path)
    assert health == {"schema_version": 1, "sources": {}}
    assert load_health(None) == {"schema_version": 1, "sources": {}}


def _config_with_health(tmp_path, d=None):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    cfg = {
        "schema_version": 1,
        "sources": [
            {"id": "a", "name": "A", "url": "https://a.example/sub", "category": "universal"},
            {"id": "b", "name": "B", "url": "https://b.example/sub", "category": "universal"},
        ],
        "paths": {
            "subscription_base64": "FL1PVPN",
            "subscription_raw": "sub.txt",
            "stats": "stats.json",
            "history": "data/h.json",
            "source_health": "data/source_health.json",
            "countries": "config/c.json",
        },
        "target_count": 1,
        "min_publish_count": 1,
        "max_candidates": 5,
        "category_quotas": {"universal": 1, "whitelist": 0},
        "preferred_countries": ["DE"],
        "fetch_workers": 1,
        "probe_workers": 1,
        "verify_workers": 1,
        "source_timeout_seconds": 5,
        "tcp_timeout_seconds": 1,
        "udp_timeout_seconds": 1,
        "verify_timeout_seconds": 5,
        "speed_test_bytes": 0,
    }
    f = config_dir / "subscription.json"
    f.write_text(json.dumps(cfg))
    (config_dir / "c.json").write_text(json.dumps({"DE": "Германия"}))
    health_file = data_dir / "source_health.json"
    if d is not None:
        health_file.write_text(json.dumps(d))
    return f, health_file


def test_find_and_prune_dead_sources(tmp_path):
    health = {
        "schema_version": 1,
        "sources": {
            "a": {"fail_streak": 40},
            "b": {"fail_streak": 1},
        },
    }
    config_file, health_file = _config_with_health(tmp_path, health)
    alive, dead = find_dead_sources(config_file, fail_streak=36)
    assert [s.source_id for s in dead] == ["a"]
    assert [s.source_id for s in alive] == ["b"]
    # без --apply конфиг не меняется
    prune_dead_sources(config_file, fail_streak=36, apply=False)
    assert len(json.loads(config_file.read_text())["sources"]) == 2
    alive, dead = prune_dead_sources(config_file, fail_streak=36, apply=True)
    assert [s.source_id for s in alive] == ["b"]
    remaining = [s["id"] for s in json.loads(config_file.read_text())["sources"]]
    assert remaining == ["b"]


def test_prune_refuses_to_remove_all(tmp_path):
    health = {"schema_version": 1, "sources": {"a": {"fail_streak": 9}, "b": {"fail_streak": 9}}}
    config_file, _ = _config_with_health(tmp_path, health)
    with pytest.raises(ConfigError):
        prune_dead_sources(config_file, fail_streak=3, apply=True)

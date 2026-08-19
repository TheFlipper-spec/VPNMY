import json
from pathlib import Path

import pytest

from vpnmy.cli import main
from vpnmy.config import ConfigError
from vpnmy.sources import add_source, list_sources, remove_source, set_source_enabled


def _config(tmp_path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "sources": [
            {
                "id": "one",
                "name": "Первый",
                "url": "https://example.com/one",
                "category": "universal",
                "enabled": True,
            }
        ],
        "paths": {
            "subscription_base64": "a",
            "subscription_raw": "b",
            "stats": "c",
            "history": "d",
            "countries": "e",
        },
        "target_count": 3,
        "min_publish_count": 1,
        "max_candidates": 10,
        "max_per_endpoint": 1,
        "category_quotas": {"universal": 3},
        "preferred_countries": ["RU"],
        "fetch_workers": 1,
        "probe_workers": 1,
        "verify_workers": 1,
        "source_timeout_seconds": 5,
        "tcp_timeout_seconds": 1,
        "verify_timeout_seconds": 5,
        "speed_test_bytes": 0,
        "xray_bin": "xray",
    }
    path = tmp_path / "config" / "subscription.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_add_and_remove_source(tmp_path):
    path = _config(tmp_path)
    added = add_source(path, "https://cdn.example.com/sub.txt", name="CDN", category="whitelist")
    assert added.source_id == "cdn-example-com"
    assert added.category == "whitelist"
    assert len(list_sources(path)) == 2
    removed = remove_source(path, "cdn.example.com")
    assert removed.source_id == "cdn-example-com"
    assert [item.source_id for item in list_sources(path)] == ["one"]


def test_cannot_remove_last_source(tmp_path):
    path = _config(tmp_path)
    with pytest.raises(ConfigError):
        remove_source(path, "one")


def test_disable_and_enable(tmp_path):
    path = _config(tmp_path)
    add_source(path, "https://two.example.com/sub", name="Второй")
    disabled = set_source_enabled(path, "two-example-com", False)
    assert disabled.enabled is False
    enabled = set_source_enabled(path, "https://two.example.com/sub", True)
    assert enabled.enabled is True


def test_duplicate_url_rejected(tmp_path):
    path = _config(tmp_path)
    with pytest.raises(ConfigError):
        add_source(path, "https://example.com/one")


def test_cli_sources_list_and_add(tmp_path, capsys):
    path = _config(tmp_path)
    assert main(["--config", str(path), "sources"]) == 0
    listed = capsys.readouterr().out
    assert "one" in listed
    assert main(["--config", str(path), "sources", "add", "https://new.example.com/s", "--name", "Новый"]) == 0
    assert "new-example-com" in capsys.readouterr().out
    assert any(item.source_id == "new-example-com" for item in list_sources(path))

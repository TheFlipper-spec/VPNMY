import json
from pathlib import Path

import pytest

from vpnmy.config import ConfigError, load_config


def data():
    return {
        "schema_version": 1,
        "sources": [
            {"id": "x", "name": "X", "url": "https://example.com/s", "category": "universal"}
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


def write(tmp_path: Path, d):
    p = tmp_path / "config"
    p.mkdir()
    f = p / "subscription.json"
    f.write_text(json.dumps(d))
    return f


def test_valid(tmp_path):
    assert load_config(write(tmp_path, data())).target_count == 3


def test_http_rejected(tmp_path):
    d = data()
    d["sources"][0]["url"] = "http://example.com"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, d))


def test_escape_rejected(tmp_path):
    d = data()
    d["paths"]["stats"] = "../x"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, d))


def test_new_smart_defaults(tmp_path):
    c = load_config(write(tmp_path, data()))
    assert c.max_nodes_per_source == 160
    assert c.source_fail_threshold == 6
    assert c.stable_streak_required == 2
    assert c.max_per_subnet == 2
    assert c.hysteria_bin
    assert c.paths.source_health is not None
    assert c.udp_timeout_seconds == 1.5


def test_project_config_contains_requested_sources():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/subscription.json")
    sources = {source.source_id: source.url for source in config.sources}
    assert len(sources) == 9
    assert any("gitverse.ru/api/repos/SlavaKat/FreeProxyNova" in url for url in sources.values())
    assert "https://sub.vlessfo.ru/vlessforu/working_configs.txt" in sources.values()
    assert "https://abscloud.lol/connect.php?uid=1909141964" in sources.values()
    assert all("WHITE-SNI-RU" not in url for url in sources.values())
    assert any("V2RayAggregator" in url for url in sources.values())
    assert any("TV2Ray" in url for url in sources.values())
    assert any("v2ray-configs" in url for url in sources.values())
    assert any(url.endswith("hysteria2.txt") for url in sources.values())
    assert config.profile_title == "FL1P VPN"
    assert config.max_nodes_per_source > 0 and config.stable_streak_required >= 1


def test_duplicate_source_url_rejected(tmp_path):
    d = data()
    d["sources"].append(
        {"id": "y", "name": "Y", "url": "https://example.com/s", "category": "whitelist"}
    )
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, d))

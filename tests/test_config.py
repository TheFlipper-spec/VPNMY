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


def test_source_fields_must_really_be_strings(tmp_path):
    d = data()
    d["sources"][0]["name"] = 123
    with pytest.raises(ConfigError, match="должны быть строками"):
        load_config(write(tmp_path, d))


def test_country_codes_must_be_unique_ascii_iso_codes(tmp_path):
    d = data()
    d["preferred_countries"] = ["ru", "RU"]
    config_file = write(tmp_path, d)
    with pytest.raises(ConfigError, match="повторяющиеся"):
        load_config(config_file)

    d["preferred_countries"] = ["ДЕ"]
    config_file.write_text(json.dumps(d))
    with pytest.raises(ConfigError, match="двухбуквенных"):
        load_config(config_file)


def test_project_config_contains_requested_sources():
    root = Path(__file__).resolve().parents[1]
    sources = {
        source.source_id: source.url
        for source in load_config(root / "config/subscription.json").sources
    }
    assert sources["vlessforu"] == "https://sub.vlessfo.ru/vlessforu/working_configs.txt"
    assert sources["vedalink"] == "https://vedalink.xyz/sub/fJXfBACAy_fPp8Hr"

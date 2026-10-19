import json
from unittest.mock import patch

from vpnmy.builder import BuildError
from vpnmy.cli import main


def test_cli_help():
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0


def test_cli_invalid_config():
    assert main(["--config", "nonexistent.json"]) == 1


def test_cli_dry_run(tmp_path, countries_file):
    config_data = {
        "schema_version": 1,
        "sources": [
            {
                "id": "test",
                "name": "Test",
                "url": "https://example.com/sub",
                "category": "universal",
            }
        ],
        "paths": {
            "subscription_base64": "FL1PVPN",
            "subscription_raw": "subscription.txt",
            "stats": "stats.json",
            "history": "health_history.json",
            "countries": str(countries_file),
        },
        "target_count": 3,
        "min_publish_count": 1,
        "max_candidates": 10,
        "max_per_endpoint": 1,
        "category_quotas": {"universal": 2, "whitelist": 1},
        "preferred_countries": ["DE"],
        "fetch_workers": 1,
        "probe_workers": 1,
        "verify_workers": 1,
        "source_timeout_seconds": 5,
        "tcp_timeout_seconds": 1,
        "verify_timeout_seconds": 5,
        "speed_test_bytes": 0,
        "xray_bin": "xray",
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config_data))

    from vpnmy.builder import BuildReport

    report = BuildReport(1, 1, 1, 1, 1, 1, "healthy", "tcp_only")
    with patch("vpnmy.cli.build_subscription", return_value=report):
        res = main(["--config", str(cfg_file), "--dry-run", "--skip-deep-check"])
        assert res == 0


def _minimal_config(tmp_path, countries_file):
    config_data = {
        "schema_version": 1,
        "sources": [
            {
                "id": "test",
                "name": "Test",
                "url": "https://example.com/sub",
                "category": "universal",
            }
        ],
        "paths": {
            "subscription_base64": "FL1PVPN",
            "subscription_raw": "subscription.txt",
            "stats": "stats.json",
            "history": "health_history.json",
            "countries": str(countries_file),
        },
        "target_count": 3,
        "min_publish_count": 1,
        "max_candidates": 10,
        "max_per_endpoint": 1,
        "category_quotas": {"universal": 3},
        "preferred_countries": ["DE"],
        "fetch_workers": 1,
        "probe_workers": 1,
        "verify_workers": 1,
        "source_timeout_seconds": 5,
        "tcp_timeout_seconds": 1,
        "verify_timeout_seconds": 5,
        "speed_test_bytes": 0,
        "xray_bin": "xray",
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config_data))
    return cfg_file


def test_cli_degraded_build_exit_codes(tmp_path, countries_file):
    cfg_file = _minimal_config(tmp_path, countries_file)
    with patch("vpnmy.cli.build_subscription", side_effect=BuildError("мало узлов")):
        assert main(["--config", str(cfg_file)]) == 1
    with patch("vpnmy.cli.build_subscription", side_effect=BuildError("мало узлов")):
        assert main(["--config", str(cfg_file), "--allow-degraded"]) == 0

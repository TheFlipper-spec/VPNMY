import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vpnmy.artifacts import ArtifactError, main, validate_artifacts
from vpnmy.config import BuildConfig, Paths
from vpnmy.models import CheckResult, Source
from vpnmy.parser import parse_link
from vpnmy.publisher import atomic_publish, build_payloads


def published_files(tmp_path: Path, countries_file: Path) -> Paths:
    paths = Paths(
        tmp_path / "FL1PVPN",
        tmp_path / "subscription.txt",
        tmp_path / "stats.json",
        tmp_path / "history.json",
        countries_file,
    )
    source = Source("test", "Test", "https://example.com/sub", "universal")
    config = BuildConfig(
        (source,),
        paths,
        1,
        1,
        10,
        1,
        {"universal": 1},
        ("DE",),
        1,
        1,
        1,
        5,
        1,
        5,
        0,
        "xray",
    )
    node = parse_link(
        "vless://123e4567-e89b-12d3-a456-426614174000@1.1.1.1:443"
        "?encryption=none&security=tls&type=ws&sni=example.com",
        source,
    )
    result = CheckResult(
        node,
        10,
        20,
        1.5,
        "DE",
        "2026-01-01T00:00:00Z",
        resolved_ip="1.1.1.1",
        checks_passed=2,
    )
    payloads = build_payloads(
        [result],
        config=config,
        countries={"DE": "Германия"},
        history={"schema_version": 1, "nodes": {}},
        source_stats=[],
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        check_mode="xray",
    )
    atomic_publish(payloads)
    return paths


def test_production_validation_counts_only_vpn_links(tmp_path, countries_file):
    paths = published_files(tmp_path, countries_file)

    summary = validate_artifacts(
        paths.subscription_base64,
        paths.subscription_raw,
        paths.stats,
        production=True,
        min_count=1,
    )

    assert summary.total == 1
    assert summary.metadata_lines == 0
    assert len(paths.subscription_raw.read_text().splitlines()) == summary.total


def test_validation_reports_stats_mismatch(tmp_path, countries_file):
    paths = published_files(tmp_path, countries_file)
    stats = json.loads(paths.stats.read_text())
    stats["total"] = 2
    paths.stats.write_text(json.dumps(stats))

    with pytest.raises(ArtifactError, match="число VPN URI"):
        validate_artifacts(paths.subscription_base64, paths.subscription_raw, paths.stats)


def test_cli_returns_error_instead_of_assertion(tmp_path, countries_file, capsys):
    paths = published_files(tmp_path, countries_file)
    paths.subscription_base64.write_text("not base64", encoding="ascii")
    config_path = tmp_path / "subscription.json"
    config_path.write_text(
        json.dumps(
            {
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
                    "history": "history.json",
                    "countries": str(countries_file),
                },
                "target_count": 1,
                "min_publish_count": 1,
                "max_candidates": 1,
                "max_per_endpoint": 1,
                "category_quotas": {"universal": 1},
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
        )
    )

    assert main(["--config", str(config_path)]) == 1
    assert "Ошибка проверки артефактов" in capsys.readouterr().out

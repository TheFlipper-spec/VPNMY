import base64
import json
from datetime import UTC, datetime

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
    r = CheckResult(n, 20, 50, 10, "DE", "2026-01-01T00:00:00Z", 90)
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
    assert json.loads(paths.stats.read_text())["total"] == 1

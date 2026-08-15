import base64
import json
from pathlib import Path

import pytest

from vpnmy.fetcher import _validate_remote_url, fetch_all
from vpnmy.history import empty_history, load_history
from vpnmy.models import Source
from vpnmy.parser import deduplicate, parse_link
from vpnmy.publisher import country_flag
from vpnmy.xray import XrayError, build_xray_config

UUID = "123e4567-e89b-12d3-a456-426614174000"
SOURCE = Source("test", "Test", "https://example.com/sub", "universal")


def vmess(**changes):
    payload = {
        "v": "2",
        "ps": "Реклама",
        "add": "Example.COM.",
        "port": "443",
        "id": UUID,
        "aid": "0",
        "net": "ws",
        "host": "cdn.example.com",
        "path": "/vpn",
        "tls": "tls",
    }
    payload.update(changes)
    return "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()


def test_vmess_dedup_uses_normalized_effective_config():
    first = parse_link(vmess(), SOURCE)
    second = parse_link(vmess(ps="Другое имя", port=443, ignored_advertising="channel"), SOURCE)

    assert first.node_id == second.node_id
    assert len(deduplicate([first, second])) == 1


def test_xray_uses_ip_from_tcp_probe_but_keeps_tls_name():
    node = parse_link(
        f"vless://{UUID}@server.example.com:443?encryption=none&security=tls&type=ws&sni=tls.example.com",
        SOURCE,
    )
    outbound = build_xray_config(node, 1080, server_address="1.1.1.1")["outbounds"][0]

    assert outbound["settings"]["vnext"][0]["address"] == "1.1.1.1"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "tls.example.com"
    with pytest.raises(XrayError):
        build_xray_config(node, 1080, server_address="127.0.0.1")


def test_fetcher_rejects_unsafe_redirect_targets():
    with pytest.raises(ValueError):
        _validate_remote_url("http://example.com/sub")
    with pytest.raises(ValueError):
        _validate_remote_url("https://127.0.0.1/sub")
    assert fetch_all((Source("off", "Off", "https://example.com", "universal", False),), 1, 1) == []


def test_corrupt_history_root_and_rows_are_reset(tmp_path: Path):
    history_path = tmp_path / "history.json"
    history_path.write_text("[]")
    assert load_history(history_path) == empty_history()

    history_path.write_text(
        json.dumps({"schema_version": 1, "nodes": {"bad": {"successes": "many"}}})
    )
    assert load_history(history_path) == empty_history()


def test_country_flag_accepts_only_ascii_iso_code():
    assert country_flag("DE") == "🇩🇪"
    assert country_flag("ДЕ") == "🌐"

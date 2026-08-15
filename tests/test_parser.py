import base64
import json

import pytest

from vpnmy.parser import ParseError, deduplicate, extract_links, parse_link, parse_source

UUID = "123e4567-e89b-12d3-a456-426614174000"


def vless(host="1.1.1.1", fragment="Germany"):
    return f"vless://{UUID}@{host}:443?encryption=none&security=reality&type=tcp&sni=example.com&pbk=key#{fragment}"


def test_base64():
    raw = vless() + "\n" + vless("8.8.8.8") + "\n"
    assert extract_links(base64.b64encode(raw.encode()).decode()) == raw.strip().splitlines()


def test_fragment_space(source):
    n, r = parse_source(vless(fragment="Fast node one"), source)
    assert not r and n[0].original_name == "Fast node one"


def test_private_rejected(source):
    with pytest.raises(ParseError):
        parse_link(vless("127.0.0.1"), source)


def test_reality_requires_key(source):
    with pytest.raises(ParseError):
        parse_link(f"vless://{UUID}@1.1.1.1:443?security=reality&sni=x", source)


def test_vmess(source):
    d = {
        "v": "2",
        "ps": "Old",
        "add": "1.1.1.1",
        "port": "443",
        "id": UUID,
        "aid": "0",
        "net": "ws",
        "tls": "tls",
    }
    n = parse_link("vmess://" + base64.b64encode(json.dumps(d).encode()).decode(), source)
    out = json.loads(base64.b64decode(n.link_with_name("Новый").removeprefix("vmess://")))
    assert out["ps"] == "Новый"


def test_dedup(source):
    a = parse_link(vless(), source)
    b = parse_link(vless(fragment="x"), source)
    assert len(deduplicate([a, b])) == 1

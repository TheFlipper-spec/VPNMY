from vpnmy.models import Source
from vpnmy.parser import parse_link
from vpnmy.xray import build_xray_config

UUID = "123e4567-e89b-12d3-a456-426614174000"
S = Source("s", "S", "https://x", "universal")


def test_grpc_reality():
    n = parse_link(
        f"vless://{UUID}@1.1.1.1:443?encryption=none&security=reality&type=grpc&sni=x.com&pbk=key&serviceName=svc",
        S,
    )
    o = build_xray_config(n, 1234)["outbounds"][0]
    assert o["streamSettings"]["grpcSettings"]["serviceName"] == "svc"


def test_ws_tls():
    n = parse_link(
        f"vless://{UUID}@1.1.1.1:443?encryption=none&security=tls&type=ws&sni=x.com&host=cdn.com&path=%2Fvpn",
        S,
    )
    assert build_xray_config(n, 1)["outbounds"][0]["streamSettings"]["wsSettings"]["path"] == "/vpn"

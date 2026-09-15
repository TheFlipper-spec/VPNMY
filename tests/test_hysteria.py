import importlib.util
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from vpnmy import tunnel, xray
from vpnmy.hysteria import build_hysteria_config, resolve_hysteria, verify_node
from vpnmy.models import ProbeResult, Source
from vpnmy.parser import ParseError, deduplicate, parse_link, parse_source
from vpnmy.verifier import verify_all

S = Source("s", "S", "https://x", "universal")
HY = "hysteria2://pass%3Aword@1.1.1.1:8443/?sni=a.example&insecure=1&obfs=salamander&obfs-password=secret#DE-1"


def test_parse_hysteria2_and_alias():
    node = parse_link(HY, S)
    assert node.scheme == "hysteria2"
    assert node.is_hysteria
    assert node.transport == "hysteria2"
    assert node.security == "tls"
    assert node.user == "pass:word"
    assert node.options["obfs"] == "salamander"
    assert node.options["obfs-password"] == "secret"
    assert node.options["insecure"] == "1"
    aliased = parse_link("hy2://pw@1.1.1.1:443/?sni=x.com#x", S)
    assert aliased.scheme == "hysteria2"
    assert aliased.original_link.startswith("hy2://")
    assert aliased.link_with_name("Узел").startswith("hy2://")
    assert deduplicate([node, aliased])  # без падений


def test_noauth_hysteria():
    node = parse_link("hysteria2://2.2.2.2:443/?sni=x.com#n", S)
    assert node.user == ""
    assert build_hysteria_config(node, 10)["server"] == "2.2.2.2:443"


def test_port_hopping():
    node = parse_link(
        "hysteria2://pw@3.3.3.3:443/?mport=20000-30000&sni=x.com&alpn=h3,h3-29#n", S
    )
    assert node.probe_port == 20000
    config = build_hysteria_config(node, 10)
    assert config["server"] == "3.3.3.3:20000-30000"
    assert config["tls"]["alpn"] == ["h3", "h3-29"]


def test_obfs_must_be_salamander():
    with pytest.raises(ParseError):
        parse_link("hysteria2://pw@1.1.1.1:443/?obfs=wechat#x", S)
    with pytest.raises(ParseError):
        parse_link("hysteria2://pw@1.1.1.1:443/?obfs=salamander#x", S)


def test_pin_sha256_and_config_fields():
    node = parse_link(
        "hysteria2://pw@1.1.1.1:443/?pinSHA256=abc123&sni=x.com#x",
        S,
    )
    tls = build_hysteria_config(node, 10)["tls"]
    assert tls["pinSHA256"] == "abc123"
    assert tls["sni"] == "x.com"
    assert "insecure" not in tls


def test_hysteria_links_extracted_from_base64():
    import base64

    blob = base64.b64encode(HY.encode()).decode()
    nodes, rejected = parse_source(blob, S)
    assert rejected == 0 and len(nodes) == 1


def test_config_is_lazy_socks5():
    node = parse_link(HY, S)
    config = build_hysteria_config(node, 10808)
    assert config["lazy"] is True
    assert config["socks5"]["listen"] == "127.0.0.1:10808"
    assert config["obfs"]["salamander"]["password"] == "secret"
    # JSON-разметка обязана быть валидным JSON (YAML-парсер клиента её принимает)
    assert json.loads(json.dumps(config)) == config


def test_resolve_missing_binary():
    assert resolve_hysteria("/nonexistent/hysteria-xyz") is None


# --- фейковое ядро (SOCKS5 no-auth CONNECT) и локальные HTTP-цели ---

FAKE_CORE = r"""
import json, socket, struct, sys, threading

def read_config():
    args = sys.argv[1:]
    path = args[args.index("-c") + 1]
    raw = open(path, encoding="utf-8").read()
    cfg = json.loads(raw)
    if "inbounds" in cfg:
        return int(cfg["inbounds"][0]["port"])
    return int(cfg["socks5"]["listen"].rsplit(":", 1)[1])

def relay(a, b):
    try:
        while True:
            data = a.recv(65535)
            if not data:
                break
            b.sendall(data)
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    except OSError:
        pass

class Reader:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
    def take(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65535)
            if not chunk:
                raise OSError("eof")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

def handle(client):
    try:
        reader = Reader(client)
        _ver, nmethods = reader.take(2)
        reader.take(nmethods)
        client.sendall(b"\x05\x00")
        ver, cmd, rsv, atyp = reader.take(4)
        if atyp == 1:
            host = socket.inet_ntoa(reader.take(4))
        elif atyp == 3:
            (length,) = reader.take(1)
            host = reader.take(length).decode()
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6, reader.take(16))
        else:
            return
        port = struct.unpack("!H", reader.take(2))[0]
        upstream = socket.create_connection((host, port), timeout=5)
        client.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
        if reader.buf:
            upstream.sendall(reader.buf)
        t1 = threading.Thread(target=relay, args=(client, upstream), daemon=True)
        t2 = threading.Thread(target=relay, args=(upstream, client), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
        client.close(); upstream.close()
    except OSError:
        client.close()

port = read_config()
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", port))
server.listen(64)
while True:
    conn, _ = server.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _body(self, body: bytes, content_type: str = "text/plain", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/trace"):
            self._body(b"fl=123\nip=1.1.1.1\nloc=DE\n")
        elif self.path.startswith("/204"):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/speed"):
            self._body(b"x" * 4096, "application/octet-stream")
        else:
            self._body(b"not found", status=404)


@pytest.fixture
def fake_core(tmp_path: Path):
    binary = tmp_path / "fakecore"
    binary.write_text("#!/usr/bin/env python3\n" + FAKE_CORE)
    binary.chmod(0o755)
    return binary


@pytest.fixture
def targets(monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(tunnel, "TRACE_URL", f"http://127.0.0.1:{port}/trace")
    monkeypatch.setattr(
        tunnel, "CONFIRMATION_TARGETS", ((f"http://127.0.0.1:{port}/204", frozenset({204}), None),)
    )
    monkeypatch.setattr(tunnel, "SPEED_URL", f"http://127.0.0.1:{port}/speed?bytes={{n}}")
    yield port
    httpd.shutdown()


def test_hysteria_verify_end_to_end(fake_core, targets):
    node = parse_link(HY, S)
    probe = ProbeResult(node, 10, resolved_ip="1.1.1.1")
    result = verify_node(
        probe, hysteria_bin=str(fake_core), timeout=6, speed_test_bytes=4096
    )
    assert result is not None
    assert result.country == "DE"
    assert result.checks_passed == 2
    assert result.node.is_hysteria
    assert result.speed_mbps > 0


def test_xray_verify_end_to_end(fake_core, targets):
    node = parse_link(
        "vless://123e4567-e89b-12d3-a456-426614174000@1.1.1.1:443?encryption=none&security=tls&type=tcp&sni=x.com#DE",
        S,
    )
    probe = ProbeResult(node, 10, resolved_ip="1.1.1.1")
    result = xray.verify_node(
        probe, xray_bin=str(fake_core), timeout=6, speed_test_bytes=4096
    )
    assert result is not None
    assert result.country == "DE"
    assert result.node.scheme == "vless"


def test_verify_dispatch_and_skip(fake_core, targets):
    hy_node = parse_link(HY, S)
    vless_node = parse_link(
        "vless://123e4567-e89b-12d3-a456-426614174000@1.1.1.1:443?encryption=none&security=tls&type=tcp&sni=x.com#DE",
        S,
    )
    probes = [ProbeResult(hy_node, 10, resolved_ip="1.1.1.1"),
              ProbeResult(vless_node, 10, resolved_ip="1.1.1.2")]
    verified, failed, skipped = verify_all(
        probes,
        xray_bin=str(fake_core),
        hysteria_bin=str(fake_core),
        timeout=6,
        speed_test_bytes=0,
        workers=2,
    )
    assert {r.node.scheme for r in verified} == {"vless", "hysteria2"}
    assert not failed and not skipped
    # без бинаря hysteria hy2-узлы пропускаются и не считаются отказом
    verified2, failed2, skipped2 = verify_all(
        [probes[0]], xray_bin=str(fake_core), hysteria_bin=None,
        timeout=6, speed_test_bytes=0, workers=1,
    )
    assert not verified2 and not failed2 and len(skipped2) == 1


def test_udp_probe_live_and_closed():
    from unittest.mock import patch

    from vpnmy import probe as probe_mod

    node = parse_link(HY, S)
    real_getaddrinfo = socket.getaddrinfo

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    udp_port = server.getsockname()[1]

    def answer():
        server.settimeout(3)
        try:
            while True:
                _data, addr = server.recvfrom(2048)
                server.sendto(b"\x0f" * 16, addr)
        except OSError:
            pass

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()

    def fake_infos(_host, _port, family=0, type=0, proto=0, flags=0):
        return real_getaddrinfo(
            "127.0.0.1", udp_port, family=socket.AF_UNSPEC, type=socket.SOCK_DGRAM
        )

    with patch("vpnmy.probe.socket.getaddrinfo", side_effect=fake_infos):
        alive = probe_mod._probe_udp(node, 1.0)
    assert alive is not None and alive.resolved_ip == "127.0.0.1"
    server.close()

    # Закрытый UDP-порт: либо ICMP unreachable (None), либо консервативный
    # fallback с большой задержкой — но никогда не «быстрый живой» результат.
    with patch("vpnmy.probe.socket.getaddrinfo", side_effect=fake_infos):
        dead = probe_mod.probe_node(
            parse_link(f"hysteria2://pw@8.8.8.8:{udp_port}/#x", S), 1.0, 0.8
        )
    assert dead is None or dead.tcp_ms >= 800


def test_tcp_probe_still_works_for_classic():
    from unittest.mock import patch

    from vpnmy import probe as probe_mod
    from vpnmy.parser import parse_link as pl

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    listen_port = server.getsockname()[1]
    for _ in range(4):
        threading.Thread(target=server.accept, daemon=True).start()

    node = pl(
        "vless://123e4567-e89b-12d3-a456-426614174000@8.8.8.8:443?encryption=none&security=tls&type=tcp&sni=x.com#x",
        S,
    )
    real_getaddrinfo = socket.getaddrinfo

    def fake_addresses(_host, _port):
        return [
            (family, socktype, proto, sockaddr)
            for family, socktype, proto, _name, sockaddr in real_getaddrinfo(
                "127.0.0.1", listen_port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
        ]

    with patch("vpnmy.probe._public_addresses", side_effect=fake_addresses):
        result = probe_mod._probe_tcp(node, 1.0)
    assert result is not None
    server.close()


def test_builder_publishes_hysteria(fake_core, targets, tmp_path, monkeypatch):
    # используем минимальный countries-файл из tmp
    countries = tmp_path / "countries.json"
    countries.write_text(json.dumps({"DE": "Германия"}))
    from vpnmy.builder import build_subscription
    from vpnmy.config import BuildConfig, Paths
    from vpnmy.fetcher import FetchResult

    sources = (Source("hy", "Hy", "https://x/hy", "universal"),)
    paths = Paths(
        tmp_path / "b64",
        tmp_path / "raw",
        tmp_path / "stats",
        tmp_path / "hist",
        countries,
        tmp_path / "source_health.json",
    )
    config = BuildConfig(
        sources,
        paths,
        3,
        1,
        10,
        1,
        {"universal": 2, "whitelist": 0},
        ("DE",),
        2,
        8,
        4,
        5,
        1.0,
        6,
        4096,
        "xray",
        hysteria_bin=str(fake_core),
    )
    import vpnmy.builder as builder_mod
    from vpnmy.models import ProbeResult

    monkeypatch.setattr(builder_mod, "resolve_xray", lambda _: str(fake_core))
    monkeypatch.setattr(builder_mod, "resolve_hysteria", lambda _: str(fake_core))
    payload = "\n".join(
        [
            "hysteria2://pw1@1.1.1.1:443/?sni=a.example&insecure=1#DE-1",
            "hysteria2://pw2@2.2.2.2:443/?sni=b.example&insecure=1#DE-2",
        ]
    )
    monkeypatch.setattr(
        builder_mod, "fetch_all", lambda sources, t, w: [FetchResult(sources[0], payload, 1)]
    )
    monkeypatch.setattr(
        builder_mod,
        "probe_all",
        lambda ns, tcp, udp, w: [ProbeResult(n, 30, resolved_ip=n.host) for n in ns],
    )
    report = build_subscription(config)
    assert report.published >= 1
    raw = paths.subscription_raw.read_text(encoding="utf-8")
    assert "hysteria2://" in raw
    stats = json.loads(paths.stats.read_text())
    assert stats["protocols"] == {"HYSTERIA2": report.published}
    health = json.loads(paths.source_health.read_text())
    assert "hy" in health["sources"] and health["sources"]["hy"]["fail_streak"] == 0


def test_dead_core_returns_none(tmp_path):
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    node = parse_link(HY, S)
    probe = ProbeResult(node, 10)
    assert verify_node(probe, hysteria_bin=str(broken), timeout=3, speed_test_bytes=0) is None


OFFICIAL_VERSION_OUTPUT = """
 / / / /_  __
/_/ /_/ /_/ /
Aperture Internet Laboratory
Version: 2.12.2
BuildType: release
Toolchain: go1.26.1
Dependency: quic-go=v0.59.0
"""


def test_resolve_official_version_output(tmp_path):
    binary = tmp_path / "hysteria"
    binary.write_text("#!/bin/sh\ncat <<'EOF'\n" + OFFICIAL_VERSION_OUTPUT + "EOF\n")
    binary.chmod(0o755)
    assert "hysteria" not in OFFICIAL_VERSION_OUTPUT.lower()
    assert resolve_hysteria(str(binary)) == str(binary)


def test_resolve_rejects_name_only(tmp_path):
    binary = tmp_path / "hysteria"
    binary.write_text("#!/bin/sh\necho hysteria\n")
    binary.chmod(0o755)
    assert resolve_hysteria(str(binary)) is None


def test_installer_output_looks_valid():
    from vpnmy.hysteria import VERSION_MARKERS

    path = Path(__file__).resolve().parents[1] / "scripts" / "install_hysteria.py"
    spec = importlib.util.spec_from_file_location("install_hysteria", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VERSION_MARKERS == VERSION_MARKERS
    assert module.output_looks_valid(OFFICIAL_VERSION_OUTPUT)
    for marker in VERSION_MARKERS:
        assert module.output_looks_valid(marker.upper())
    for invalid in ("", "hysteria", "not a client", "unknown command version"):
        assert not module.output_looks_valid(invalid)

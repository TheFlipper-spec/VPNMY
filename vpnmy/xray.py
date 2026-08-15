from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .models import CheckResult, Node, ProbeResult

LOGGER = logging.getLogger(__name__)
_TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
_SPEED_URL = "https://speed.cloudflare.com/__down?bytes={bytes_count}"


class XrayError(RuntimeError):
    """Xray отсутствует или не может проверить конфигурацию."""


def resolve_xray(binary: str) -> str:
    candidate = shutil.which(binary)
    if candidate is None and Path(binary).is_file():
        candidate = str(Path(binary).resolve())
    if candidate is None or not os.access(candidate, os.X_OK):
        raise XrayError(
            f"Xray не найден: {binary}. Установите Xray или используйте --skip-deep-check только для диагностики."
        )
    try:
        completed = subprocess.run(
            [candidate, "version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise XrayError(f"не удалось запустить Xray: {exc}") from exc
    if completed.returncode != 0 or "Xray" not in completed.stdout:
        raise XrayError("исполняемый файл Xray не прошёл проверку версии")
    return candidate


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _alpn(value: str) -> list[str]:
    cleaned = value.strip().strip("[]")
    return [item.strip().strip("\"'") for item in cleaned.split(",") if item.strip()]


def _stream_settings(node: Node) -> dict[str, Any]:
    options = node.options
    transport = node.transport
    network = "http" if transport in {"http", "h2"} else transport
    stream: dict[str, Any] = {"network": network, "security": node.security}
    path = options.get("path") or "/"
    host = options.get("host") or ""
    if transport == "ws":
        settings: dict[str, Any] = {"path": path}
        if host:
            settings["headers"] = {"Host": host}
        stream["wsSettings"] = settings
    elif transport == "grpc":
        settings = {"serviceName": options.get("serviceName") or path.lstrip("/")}
        if options.get("authority"):
            settings["authority"] = options["authority"]
        if options.get("mode", "").lower() in {"multi", "gun"}:
            settings["multiMode"] = options.get("mode", "").lower() == "multi"
        stream["grpcSettings"] = settings
    elif transport in {"http", "h2"}:
        settings = {"path": path}
        if host:
            settings["host"] = [item.strip() for item in host.split(",") if item.strip()]
        stream["httpSettings"] = settings
    elif transport == "httpupgrade":
        settings = {"path": path}
        if host:
            settings["host"] = host
        stream["httpupgradeSettings"] = settings
    elif transport in {"xhttp", "splithttp"}:
        settings = {"path": path}
        if host:
            settings["host"] = host
        if options.get("mode"):
            settings["mode"] = options["mode"]
        stream["xhttpSettings" if transport == "xhttp" else "splithttpSettings"] = settings
    elif transport in {"tcp", "raw"}:
        header_type = options.get("headerType", "none").lower() or "none"
        stream["rawSettings" if transport == "raw" else "tcpSettings"] = {
            "header": {"type": header_type}
        }
    elif transport == "kcp":
        stream["kcpSettings"] = {"header": {"type": options.get("headerType", "none") or "none"}}
    elif transport == "quic":
        stream["quicSettings"] = {
            "security": options.get("quicSecurity", "none") or "none",
            "key": options.get("key", ""),
            "header": {"type": options.get("headerType", "none") or "none"},
        }
    if node.security == "tls":
        tls: dict[str, Any] = {
            "serverName": options.get("sni") or host or node.host,
            "allowInsecure": _truthy(options.get("allowInsecure", "0")),
            "fingerprint": options.get("fp") or "chrome",
        }
        if options.get("alpn"):
            tls["alpn"] = _alpn(options["alpn"])
        stream["tlsSettings"] = tls
    elif node.security == "reality":
        stream["realitySettings"] = {
            "show": False,
            "serverName": options.get("sni", ""),
            "fingerprint": options.get("fp") or "chrome",
            "publicKey": options.get("pbk", ""),
            "shortId": options.get("sid", ""),
            "spiderX": options.get("spx") or "/",
        }
    return stream


def build_xray_config(node: Node, local_port: int) -> dict[str, Any]:
    if node.scheme == "vless":
        user: dict[str, Any] = {"id": node.user, "encryption": "none"}
        flow = node.options.get("flow", "")
        if flow and node.transport in {"tcp", "raw"}:
            user["flow"] = flow
        outbound_settings: dict[str, Any] = {
            "vnext": [{"address": node.host, "port": node.port, "users": [user]}]
        }
    elif node.scheme == "vmess":
        try:
            alter_id = int(node.options.get("aid", "0"))
        except ValueError:
            alter_id = 0
        outbound_settings = {
            "vnext": [
                {
                    "address": node.host,
                    "port": node.port,
                    "users": [
                        {
                            "id": node.user,
                            "alterId": max(0, alter_id),
                            "security": node.options.get("scy") or "auto",
                        }
                    ],
                }
            ]
        }
    elif node.scheme == "trojan":
        outbound_settings = {
            "servers": [{"address": node.host, "port": node.port, "password": node.user}]
        }
    else:
        raise XrayError(f"неподдерживаемый протокол: {node.scheme}")
    outbound = {
        "tag": "vpn",
        "protocol": node.scheme,
        "settings": outbound_settings,
        "streamSettings": _stream_settings(node),
    }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "probe",
                "listen": "127.0.0.1",
                "port": local_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        ],
        "outbounds": [outbound],
        "routing": {"domainStrategy": "AsIs", "rules": []},
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_inbound(process: subprocess.Popen[bytes], port: int, timeout: float = 2.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def verify_node(
    probe: ProbeResult, *, xray_bin: str, timeout: float, speed_test_bytes: int
) -> CheckResult | None:
    local_port = _free_port()
    config = build_xray_config(probe.node, local_port)
    process: subprocess.Popen[bytes] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="vpnmy-xray-") as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            process = subprocess.Popen(
                [xray_bin, "run", "-c", str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if not _wait_for_inbound(process, local_port):
                return None
            proxies = {
                "http": f"socks5h://127.0.0.1:{local_port}",
                "https": f"socks5h://127.0.0.1:{local_port}",
            }
            with requests.Session() as session:
                session.trust_env = False
                session.headers["User-Agent"] = "FL1P-VPN-Healthcheck/2.0"
                started = time.perf_counter()
                response = session.get(_TRACE_URL, proxies=proxies, timeout=(3.0, timeout))
                response.raise_for_status()
                body = response.text[:16_384]
                http_ms = max(1, round((time.perf_counter() - started) * 1000))
                if "h=" not in body or "ip=" not in body:
                    return None
                match = re.search(r"(?m)^loc=([A-Z]{2})\r?$", body)
                country = match.group(1) if match else "XX"
                speed_mbps = 0.0
                if speed_test_bytes > 0:
                    try:
                        speed_started = time.perf_counter()
                        downloaded = 0
                        with session.get(
                            _SPEED_URL.format(bytes_count=speed_test_bytes),
                            proxies=proxies,
                            timeout=(3.0, timeout),
                            stream=True,
                        ) as speed_response:
                            speed_response.raise_for_status()
                            for chunk in speed_response.iter_content(chunk_size=64 * 1024):
                                downloaded += len(chunk)
                        elapsed = time.perf_counter() - speed_started
                        if downloaded and elapsed > 0:
                            speed_mbps = round(downloaded * 8 / 1_000_000 / elapsed, 2)
                    except requests.RequestException:
                        LOGGER.debug("Замер скорости недоступен для узла %s", probe.node.node_id)
                checked_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
                return CheckResult(
                    probe.node, probe.tcp_ms, http_ms, speed_mbps, country, checked_at
                )
    except (OSError, requests.RequestException, subprocess.SubprocessError, ValueError):
        return None
    finally:
        if process is not None:
            _stop(process)


def verify_all(
    probes: list[ProbeResult], *, xray_bin: str, timeout: float, speed_test_bytes: int, workers: int
) -> tuple[list[CheckResult], list[Node]]:
    verified: list[CheckResult] = []
    failed: list[Node] = []
    with ThreadPoolExecutor(
        max_workers=min(workers, max(1, len(probes))), thread_name_prefix="xray"
    ) as executor:
        futures = {
            executor.submit(
                verify_node,
                probe,
                xray_bin=xray_bin,
                timeout=timeout,
                speed_test_bytes=speed_test_bytes,
            ): probe.node
            for probe in probes
        }
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                failed.append(futures[future])
            else:
                verified.append(result)
    verified.sort(key=lambda item: (item.http_ms, item.node.node_id))
    LOGGER.info("Проверка через Xray: работают %d из %d узлов", len(verified), len(probes))
    return verified, failed

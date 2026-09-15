from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .models import CheckResult, Node, ProbeResult
from .tunnel import (
    free_port,
    http_checks_multi,
    parse_trace,
    stop_process,
    wait_for_inbound,
)

LOGGER = logging.getLogger(__name__)
# Обратная совместимость: тесты и внешний код импортируют _parse_trace отсюда.
_parse_trace = parse_trace


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


def verify_node(
    probe: ProbeResult,
    *,
    xray_bin: str,
    timeout: float,
    speed_test_bytes: int,
    attempts: int = 3,
) -> CheckResult | None:
    local_port = free_port()
    process: subprocess.Popen[bytes] | None = None
    try:
        config = build_xray_config(probe.node, local_port)
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
            if not wait_for_inbound(process, local_port):
                return None
            proxies = {
                "http": f"socks5h://127.0.0.1:{local_port}",
                "https": f"socks5h://127.0.0.1:{local_port}",
            }
            outcome = http_checks_multi(
                proxies,
                timeout=timeout,
                speed_test_bytes=speed_test_bytes,
                attempts=attempts,
                logger=LOGGER,
                node_id=probe.node.node_id,
            )
            if outcome is None:
                return None
            median_ms, max_ms, jitter_ms, country, egress_ip, speed_mbps, success_count, samples = outcome
            checked_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            return CheckResult(
                probe.node,
                probe.tcp_ms,
                median_ms,
                speed_mbps,
                country,
                checked_at,
                resolved_ip=probe.resolved_ip,
                checks_passed=2,
                egress_ip=egress_ip,
                asn="",  # обогащается позже в builder
                http_max_ms=max_ms,
                jitter_ms=jitter_ms,
                attempts=attempts,
                samples=samples,
            )
    except (OSError, requests.RequestException, subprocess.SubprocessError, ValueError, XrayError):
        return None
    finally:
        stop_process(process)

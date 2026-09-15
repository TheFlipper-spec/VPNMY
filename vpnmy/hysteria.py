"""Проверка узлов Hysteria2 официальным клиентом apernet/hysteria.

Клиент запускается с YAML-конфигом (YAML принимает также JSON-разметку),
поднимает локальный SOCKS5-inbound; дальше работает общая для всех ядер
двойная HTTPS-проверка из tunnel.py.
"""

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

from .models import CheckResult, ProbeResult
from .tunnel import free_port, http_checks_multi, stop_process, wait_for_inbound

LOGGER = logging.getLogger(__name__)
VERSION_MARKERS = ("version:", "aperture", "apernet", "quic-go")


class HysteriaError(RuntimeError):
    """Официальный клиент Hysteria отсутствует или не может проверить конфигурацию."""


def resolve_hysteria(binary: str) -> str | None:
    """Возвращает путь к клиенту Hysteria или None, если его нет (узлы hy2 пропускаются)."""
    candidate = shutil.which(binary)
    if candidate is None and Path(binary).is_file():
        candidate = str(Path(binary).resolve())
    if candidate is None or not os.access(candidate, os.X_OK):
        return None
    try:
        completed = subprocess.run(
            [candidate, "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0 or not any(
        marker in output.lower() for marker in VERSION_MARKERS
    ):
        return None
    return candidate


def _server_address(probe_node: Any) -> str:
    hopping = probe_node.options.get("mport", "")
    return f"{probe_node.host}:{hopping}" if hopping else f"{probe_node.host}:{probe_node.port}"


def build_hysteria_config(node: Any, local_port: int) -> dict[str, Any]:
    options = node.options
    config: dict[str, Any] = {
        "server": _server_address(node),
        # lazy: SOCKS5-inbound поднимается сразу, а реальное QUIC-рукопожатие
        # происходит по первому запросу — его результат и есть наша проверка.
        "lazy": True,
        "socks5": {"listen": f"127.0.0.1:{local_port}"},
        "log": {"level": "error"},
    }
    if node.user:
        config["auth"] = node.user
    tls: dict[str, Any] = {}
    sni = options.get("sni")
    if sni:
        tls["sni"] = sni
    if options.get("insecure") == "1":
        tls["insecure"] = True
    pin = options.get("pinSHA256")
    if pin:
        tls["pinSHA256"] = pin
    alpn = [item.strip() for item in options.get("alpn", "").split(",") if item.strip()]
    if alpn:
        tls["alpn"] = alpn
    if tls:
        config["tls"] = tls
    if options.get("obfs") == "salamander":
        config["obfs"] = {
            "type": "salamander",
            "salamander": {"password": options.get("obfs-password", "")},
        }
    return config


def verify_node(
    probe: ProbeResult, *, hysteria_bin: str, timeout: float, speed_test_bytes: int, attempts: int = 3
) -> CheckResult | None:
    local_port = free_port()
    process: subprocess.Popen[bytes] | None = None
    try:
        config = build_hysteria_config(probe.node, local_port)
        with tempfile.TemporaryDirectory(prefix="vpnmy-hy-") as directory:
            config_path = Path(directory) / "hysteria.yaml"
            # JSON — допустимый YAML, такой сериализатор не требует PyYAML и безопасно экранирует.
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            env = {**os.environ, "HYSTERIA_DISABLE_UPDATE_CHECK": "1"}
            process = subprocess.Popen(
                [hysteria_bin, "client", "-c", str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
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
                asn="",
                http_max_ms=max_ms,
                jitter_ms=jitter_ms,
                attempts=attempts,
                samples=samples,
            )
    except (OSError, requests.RequestException, subprocess.SubprocessError, ValueError):
        return None
    finally:
        stop_process(process)

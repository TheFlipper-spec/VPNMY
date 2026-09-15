"""Общая логика глубокой проверки через локальный SOCKS5-туннель ядра.

И Xray, и официальный клиент Hysteria поднимают локальный SOCKS5-inbound;
дальше проверка одинаковая: Cloudflare trace, независимое подтверждение
открытого интернета и короткий замер скорости.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import time

import requests

TRACE_URL = os.environ.get("VPNMY_TRACE_URL", "https://www.cloudflare.com/cdn-cgi/trace")
SPEED_URL = os.environ.get("VPNMY_SPEED_URL", "https://speed.cloudflare.com/__down?bytes={n}")
CONFIRMATION_TARGETS = (
    ("https://www.gstatic.com/generate_204", frozenset({204}), None),
    ("https://detectportal.firefox.com/success.txt", frozenset({200}), "success"),
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_inbound(process: subprocess.Popen[bytes], port: int, timeout: float = 2.5) -> bool:
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


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def parse_trace(body: str) -> tuple[str, str] | None:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and key not in fields:
            fields[key] = value.strip()
    try:
        exit_ip = ipaddress.ip_address(fields.get("ip", ""))
    except ValueError:
        return None
    country = fields.get("loc", "").upper()
    if not exit_ip.is_global or not re.fullmatch(r"[A-Z]{2}", country):
        return None
    return exit_ip.compressed, country


def _confirm_open_internet(session: requests.Session, proxies: dict[str, str], timeout: float) -> bool:
    """Второй, независимый от Cloudflare trace HTTPS-запрос через туннель."""
    request_timeout = (3.0, min(timeout, 6.0))
    for url, expected_statuses, expected_body in CONFIRMATION_TARGETS:
        try:
            with session.get(
                url,
                proxies=proxies,
                timeout=request_timeout,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code not in expected_statuses:
                    continue
                if expected_body is None:
                    return True
                body = next(response.iter_content(chunk_size=64), b"")
                if body.decode("utf-8", errors="replace").strip() == expected_body:
                    return True
        except requests.RequestException:
            continue
    return False


def http_checks(
    session: requests.Session,
    proxies: dict[str, str],
    *,
    timeout: float,
    speed_test_bytes: int,
    logger=None,
    node_id: str = "",
) -> tuple[int, str, float] | None:
    """Возвращает (http_ms, country, speed_mbps) или None, если туннель не подтверждён."""
    try:
        started = time.perf_counter()
        response = session.get(TRACE_URL, proxies=proxies, timeout=(3.0, timeout))
        response.raise_for_status()
        body = response.text[:16_384]
        http_ms = max(1, round((time.perf_counter() - started) * 1000))
        trace = parse_trace(body)
        if trace is None or not _confirm_open_internet(session, proxies, timeout):
            return None
        _exit_ip, country = trace
    except requests.RequestException:
        return None
    speed_mbps = 0.0
    if speed_test_bytes > 0:
        try:
            speed_started = time.perf_counter()
            downloaded = 0
            with session.get(
                SPEED_URL.format(n=speed_test_bytes),
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
            if logger is not None:
                logger.debug("Замер скорости недоступен для узла %s", node_id)
    return http_ms, country, speed_mbps


def make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = user_agent
    return session

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import Node, ProbeResult

LOGGER = logging.getLogger(__name__)


def _public_addresses(host: str, port: int) -> list[tuple[int, int, int, tuple]]:
    addresses: list[tuple[int, int, int, tuple]] = []
    seen: set[tuple] = set()
    for family, socktype, proto, _, sockaddr in socket.getaddrinfo(
        host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
    ):
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global or sockaddr in seen:
            continue
        seen.add(sockaddr)
        addresses.append((family, socktype, proto, sockaddr))
    return addresses


def probe_node(node: Node, timeout: float) -> ProbeResult | None:
    try:
        addresses = _public_addresses(node.host, node.port)
    except (OSError, ValueError):
        return None
    best_ms: int | None = None
    best_ip = ""
    for family, socktype, proto, sockaddr in addresses[:4]:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        started = time.perf_counter()
        try:
            sock.connect(sockaddr)
            elapsed = max(1, round((time.perf_counter() - started) * 1000))
            if best_ms is None or elapsed < best_ms:
                best_ms = elapsed
                best_ip = str(sockaddr[0])
        except OSError:
            pass
        finally:
            sock.close()
    return ProbeResult(node, best_ms, best_ip) if best_ms is not None else None


def probe_all(nodes: list[Node], timeout: float, workers: int) -> list[ProbeResult]:
    reachable: list[ProbeResult] = []
    with ThreadPoolExecutor(
        max_workers=min(workers, max(1, len(nodes))), thread_name_prefix="tcp"
    ) as executor:
        futures = [executor.submit(probe_node, node, timeout) for node in nodes]
        for future in as_completed(futures):
            try:
                result = future.result()
            except (OSError, ValueError):
                LOGGER.debug("Непредвиденная ошибка TCP-проверки", exc_info=True)
                continue
            if result is not None:
                reachable.append(result)
    reachable.sort(key=lambda item: (item.tcp_ms, item.node.node_id))
    LOGGER.info("TCP-проверка: доступны %d из %d узлов", len(reachable), len(nodes))
    return reachable

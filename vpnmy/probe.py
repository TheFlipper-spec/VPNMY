from __future__ import annotations

import ipaddress
import logging
import secrets
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


def _probe_tcp(node: Node, timeout: float) -> ProbeResult | None:
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


def _quic_version_probe() -> bytes:
    """Минимальный QUIC Initial с неподдерживаемой версией.

    RFC 9000: сервер на такой пакет обязан ответить Version Negotiation
    (для совместимых QUIC-серверов). Hysteria с obfs пакет проигнорирует —
    тогда узел остаётся кандидатом, а окончательное решение выносит
    клиент Hysteria при глубокой проверке.
    """
    dcid = secrets.token_bytes(8)
    scid = secrets.token_bytes(8)
    packet = b"".join(
        (
            b"\xc0",  # длинный заголовок, фиксированный бит, тип Initial
            b"\xde\xad\xbe\xef",  # гарантированно неподдерживаемая версия
            bytes((len(dcid),)),
            dcid,
            bytes((len(scid),)),
            scid,
            b"\x00",  # длина токена: 0
            b"\x01",  # длина оставшейся части: 1
            b"\x00",  # packet number
        )
    )
    return packet.ljust(1200, b"\x00")


def _probe_udp(node: Node, timeout: float) -> ProbeResult | None:
    port = node.probe_port
    try:
        infos = socket.getaddrinfo(
            node.host, port, family=socket.AF_UNSPEC, type=socket.SOCK_DGRAM
        )
    except (OSError, ValueError):
        return None
    packet = _quic_version_probe()
    fallback_ms = int(timeout * 1000) * 2
    best_ms: int | None = None
    best_ip = ""
    seen: set[tuple] = set()
    for family, _socktype, proto, _canonname, sockaddr in infos[:4]:
        if sockaddr in seen:
            continue
        seen.add(sockaddr)
        elapsed_ms: int | None = None
        dead = False
        for _attempt in range(2):
            sock = socket.socket(family, socket.SOCK_DGRAM, proto)
            sock.settimeout(timeout)
            try:
                sock.connect(sockaddr)
                started = time.perf_counter()
                sock.send(packet)
                try:
                    sock.recv(2048)
                    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
                    break
                except ConnectionRefusedError:
                    # ICMP port/protocol unreachable — UDP-порт точно закрыт.
                    dead = True
                    break
                except TimeoutError:
                    continue
            except OSError:
                dead = True
                break
            finally:
                sock.close()
        if dead:
            continue
        if elapsed_ms is None:
            # Нет ни ответа, ни ICMP: obfs/файрвол могут отбрасывать пробу,
            # поэтому узел сохраняется, но опускается в конец списка.
            elapsed_ms = fallback_ms
        if best_ms is None or elapsed_ms < best_ms:
            best_ms = elapsed_ms
            best_ip = str(sockaddr[0])
    return ProbeResult(node, best_ms, best_ip) if best_ms is not None else None


def probe_node(node: Node, tcp_timeout: float, udp_timeout: float) -> ProbeResult | None:
    if node.is_hysteria:
        return _probe_udp(node, udp_timeout)
    return _probe_tcp(node, tcp_timeout)


def probe_all(
    nodes: list[Node], tcp_timeout: float, udp_timeout: float, workers: int
) -> list[ProbeResult]:
    reachable: list[ProbeResult] = []
    udp_total = sum(1 for node in nodes if node.is_hysteria)
    with ThreadPoolExecutor(
        max_workers=min(workers, max(1, len(nodes))), thread_name_prefix="probe"
    ) as executor:
        futures = [
            executor.submit(probe_node, node, tcp_timeout, udp_timeout) for node in nodes
        ]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                reachable.append(result)
    reachable.sort(key=lambda item: (item.tcp_ms, item.node.node_id))
    LOGGER.info(
        "Сетевая предпроверка: доступны %d из %d узлов (UDP/Hysteria2: %d)",
        len(reachable),
        len(nodes),
        udp_total,
    )
    return reachable

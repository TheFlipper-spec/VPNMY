"""Best-effort, per-process cache of AntiFilter block lists."""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from bisect import bisect_right
from urllib.request import urlopen

LOGGER = logging.getLogger(__name__)
IP_LIST_URL = "https://antifilter.download/list/ip.lst"
DOMAIN_LIST_URL = "https://antifilter.download/list/domains.lst"
_lock = threading.Lock()
_loaded = False
# Disjoint sorted intervals, indexed separately for IPv4 and IPv6: (starts, ends).
_ip_ranges: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
_domains: frozenset[str] = frozenset()


def load_lists(*, force: bool = False) -> None:
    """Load and index lists once per process. Network errors never fail the build."""
    global _loaded, _ip_ranges, _domains
    with _lock:
        if _loaded and not force:
            return
        started = time.monotonic()
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        domains: set[str] = set()
        for url, target in ((IP_LIST_URL, networks), (DOMAIN_LIST_URL, domains)):
            try:
                with urlopen(url, timeout=12) as response:
                    lines = response.read(20_000_000).decode("utf-8", "ignore").splitlines()
                for line in lines:
                    item = line.split("#", 1)[0].strip().lower().strip(".")
                    if not item:
                        continue
                    if target is networks:
                        try:
                            networks.append(ipaddress.ip_network(item, strict=False))
                        except ValueError:
                            continue
                    else:
                        domains.add(item)
            except Exception as exc:
                LOGGER.warning("Не удалось загрузить список блокировок %s: %s", url, exc)
        indexed = {}
        for version in (4, 6):
            compressed = tuple(
                ipaddress.collapse_addresses(n for n in networks if n.version == version)
            )
            indexed[version] = (
                tuple(int(n.network_address) for n in compressed),
                tuple(int(n.broadcast_address) for n in compressed),
            )
        _ip_ranges, _domains, _loaded = indexed, frozenset(domains), True
        LOGGER.info(
            "Списки блокировок: IP-диапазонов=%d, доменов=%d; загрузка и индексация=%.2f с",
            sum(len(starts) for starts, _ends in indexed.values()),
            len(domains),
            time.monotonic() - started,
        )


def is_ip_blocked(ip: str) -> bool:
    """O(log N) interval lookup instead of scanning every blocked network."""
    load_lists()
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    starts, ends = _ip_ranges.get(address.version, ((), ()))
    value = int(address)
    index = bisect_right(starts, value) - 1
    return index >= 0 and value <= ends[index]


def is_sni_blocked(sni: str) -> bool:
    """Check exact domain and parent suffixes, independent of blocklist size."""
    load_lists()
    domain = sni.strip().lower().rstrip(".")
    while domain:
        if domain in _domains:
            return True
        domain = domain.partition(".")[2]
    return False


def reset_cache() -> None:
    """Reset cache for tests and explicit refreshes."""
    global _loaded, _ip_ranges, _domains
    with _lock:
        _loaded, _ip_ranges, _domains = False, {}, frozenset()

"""Best-effort, per-process cache of AntiFilter block lists."""
from __future__ import annotations

import ipaddress
import logging
import threading
from urllib.request import urlopen

LOGGER = logging.getLogger(__name__)
IP_LIST_URL = "https://antifilter.download/list/ip.lst"
DOMAIN_LIST_URL = "https://antifilter.download/list/domains.lst"
_lock = threading.Lock()
_loaded = False
_networks: tuple[ipaddress._BaseNetwork, ...] = ()
_domains: frozenset[str] = frozenset()


def load_lists(*, force: bool = False) -> None:
    """Load and cache lists once per process. Network errors fail open, never the build."""
    global _loaded, _networks, _domains
    with _lock:
        if _loaded and not force:
            return
        networks: list[ipaddress._BaseNetwork] = []
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
        compressed = tuple(ipaddress.collapse_addresses([n for n in networks if n.version == 4])) + tuple(
            ipaddress.collapse_addresses([n for n in networks if n.version == 6])
        )
        _networks, _domains, _loaded = compressed, frozenset(domains), True


def is_ip_blocked(ip: str) -> bool:
    load_lists()
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in _networks)


def is_sni_blocked(sni: str) -> bool:
    load_lists()
    domain = sni.strip().lower().rstrip(".")
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in _domains)


def reset_cache() -> None:
    """Reset cache for tests and explicit refreshes."""
    global _loaded, _networks, _domains
    with _lock:
        _loaded, _networks, _domains = False, (), frozenset()

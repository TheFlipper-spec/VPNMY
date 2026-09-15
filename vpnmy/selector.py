from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from .models import CheckResult, Node, ProbeResult

_TRANSPORT_SCORES = {
    # Наиболее широко поддерживаемые транспорты получают небольшой приоритет.
    "tcp": 5.0,
    "ws": 5.0,
    "grpc": 4.0,
    "httpupgrade": 3.0,
    "raw": 2.0,
    "http": 2.0,
    "h2": 2.0,
    "hysteria2": 6.0,
    "xhttp": 1.0,
    "splithttp": 1.0,
    "kcp": 0.5,
    "quic": 0.5,
}
# QUIC/маскировка особенно ценны для сложных сетей.
_PROTOCOL_BONUS = {"hysteria2": 4.0}

_COUNTRY_HINTS = {
    "russia": "RU",
    "россия": "RU",
    "finland": "FI",
    "финлянд": "FI",
    "estonia": "EE",
    "эстони": "EE",
    "latvia": "LV",
    "латви": "LV",
    "lithuania": "LT",
    "литв": "LT",
    "germany": "DE",
    "германи": "DE",
    "netherlands": "NL",
    "нидерланд": "NL",
    "poland": "PL",
    "польш": "PL",
    "france": "FR",
    "франци": "FR",
    "sweden": "SE",
    "швеци": "SE",
    "norway": "NO",
    "норвеги": "NO",
    "austria": "AT",
    "австри": "AT",
    "czech": "CZ",
    "чех": "CZ",
}


def infer_country(node: Node) -> str:
    name = node.original_name.casefold()
    for hint, code in _COUNTRY_HINTS.items():
        if hint in name:
            return code
    regional = [char for char in node.original_name if 0x1F1E6 <= ord(char) <= 0x1F1FF]
    if len(regional) >= 2:
        return "".join(chr(ord(char) - 0x1F1E6 + ord("A")) for char in regional[:2])
    match = re.search(r"(?:^|[\s|_-])([A-Z]{2})(?:$|[\s|_-])", node.original_name)
    return match.group(1) if match else "XX"


def history_row(history: dict[str, Any], node_id: str) -> dict[str, Any]:
    row = history.get("nodes", {}).get(node_id, {})
    return row if isinstance(row, dict) else {}


def is_likely_dead(node: Node, history: dict[str, Any]) -> bool:
    """Узел много раз не отвечал и почти не имел успешных проверок."""
    row = history_row(history, node.node_id)
    successes = int(row.get("successes", 0) or 0)
    failures = int(row.get("failures", 0) or 0)
    streak = int(row.get("streak", 0) or 0)
    return streak <= 0 and failures >= 4 and successes <= 1


def is_historically_unreliable(result: CheckResult, history: dict[str, Any]) -> bool:
    """Одноразовый «оживший» узел после серии отказов не сразу попадает в подписку."""
    row = history_row(history, result.node.node_id)
    successes = int(row.get("successes", 0) or 0)
    failures = int(row.get("failures", 0) or 0)
    streak = int(row.get("streak", 0) or 0)
    if failures >= 3 and streak < 2:
        return True
    total = successes + failures
    return total >= 6 and successes / total < 0.35


def is_publication_stable(
    result: CheckResult, history: dict[str, Any], required_streak: int
) -> bool:
    """Новый узел публикуется только после серии успешных глубоких проверок."""
    row = history_row(history, result.node.node_id)
    return int(row.get("streak", 0) or 0) >= max(1, required_streak)


def _hash_order(items: list[Node], slot: int, salt: str = "") -> list[Node]:
    return sorted(
        items,
        key=lambda node: hashlib.sha256(
            f"{slot}:{salt}:{node.node_id}".encode()
        ).digest(),
    )


def _stratified_sample(items: list[Node], slot: int, salt: str = "") -> list[Node]:
    """Детерминированный порядок выборки с равными долями для протокольных групп."""
    groups: dict[str, list[Node]] = defaultdict(list)
    for node in items:
        groups["hysteria2" if node.is_hysteria else "classic"].append(node)
    ordered = {group: iter(_hash_order(part, slot, salt)) for group, part in groups.items()}
    result: list[Node] = []
    # Начинаем с классической группы, если она есть, и чередуем.
    group_order = sorted(groups, key=lambda name: (name != "classic", name))
    while ordered:
        progressed = False
        for group in group_order:
            iterator = ordered.get(group)
            if iterator is None:
                continue
            try:
                result.append(next(iterator))
                progressed = True
            except StopIteration:
                ordered.pop(group, None)
        if not progressed:
            break
    return result


def cap_per_source(
    nodes: list[Node], cap: int, history: dict[str, Any], now: datetime
) -> list[Node]:
    """Ограничивает вклад одного источника, чтобы гигантские списки не затаптывали пул.

    Половину квоты отдаём узлам с историей успехов, остальное добираем
    детерминированной стратифицированной выборкой с равными долями протоколов.
    """
    if cap <= 0:
        return list(nodes)
    slot = int(now.astimezone(UTC).timestamp() // 3600)
    rows = history.get("nodes", {})
    by_source: dict[str, list[Node]] = defaultdict(list)
    for node in nodes:
        by_source[node.source_id].append(node)
    result: list[Node] = []
    for source_id, group in by_source.items():
        if len(group) <= cap:
            result.extend(group)
            continue
        known = [node for node in group if rows.get(node.node_id, {}).get("streak", 0) > 0]
        known.sort(
            key=lambda node: (
                -int(rows[node.node_id].get("streak", 0)),
                -float(rows[node.node_id].get("speed_mbps", 0) or 0),
                node.node_id,
            )
        )
        keep = known[: max(1, cap // 2)]
        kept = {node.node_id for node in keep}
        rest = [node for node in group if node.node_id not in kept]
        result.extend(keep)
        result.extend(_stratified_sample(rest, slot, f"src:{source_id}")[: cap - len(keep)])
    return result


def sample_candidates(
    nodes: list[Node], history: dict[str, Any], *, limit: int, now: datetime
) -> list[Node]:
    if len(nodes) <= limit:
        return [node for node in nodes if not is_likely_dead(node, history)] or nodes[:limit]
    rows = history.get("nodes", {})
    alive = [node for node in nodes if not is_likely_dead(node, history)]
    dead = [node for node in nodes if is_likely_dead(node, history)]
    pool = alive or nodes
    stable_limit = int(limit * 0.6)
    known = [node for node in pool if rows.get(node.node_id, {}).get("streak", 0) > 0]
    known.sort(
        key=lambda node: (
            -int(rows[node.node_id].get("streak", 0)),
            -float(rows[node.node_id].get("speed_mbps", 0)),
            node.node_id,
        )
    )
    selected = known[:stable_limit]
    selected_ids = {node.node_id for node in selected}
    slot = int(now.astimezone(UTC).timestamp() // 3600)
    exploration = [node for node in pool if node.node_id not in selected_ids]
    selected.extend(_stratified_sample(exploration, slot)[: limit - len(selected)])
    if dead and len(selected) < limit:
        recover = max(1, min(len(dead), limit // 10 or 1, limit - len(selected)))
        dead_sorted = _stratified_sample(dead, slot, "dead")
        selected.extend(dead_sorted[:recover])
    return selected


def network_key(endpoint_key: str) -> str:
    """Группа физической сети: /24 для IPv4, /48 для IPv6, хост для доменов."""
    host = endpoint_key.rpartition(":")[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.lower().rstrip(".")
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{host}/{prefix}", strict=False))


def _rank_key(rows: dict[str, Any], preferred_countries: tuple[str, ...]):
    def key(item: ProbeResult) -> tuple[float, int, int, str]:
        row = rows.get(item.node.node_id, {})
        streak = float(row.get("streak", 0))
        success = float(row.get("successes", 0))
        failure = float(row.get("failures", 0))
        reliability = (success + 1) / (success + failure + 2)
        country = str(row.get("country") or infer_country(item.node))
        try:
            country_rank = preferred_countries.index(country)
        except ValueError:
            country_rank = len(preferred_countries) + (0 if country != "XX" else 1)
        return (-(streak * 10 + reliability * 20), country_rank, item.tcp_ms, item.node.node_id)

    return key


def shortlist(
    probes: list[ProbeResult],
    history: dict[str, Any],
    category_quotas: dict[str, int],
    target_count: int,
    preferred_countries: tuple[str, ...] = (),
    *,
    max_per_subnet: int = 3,
) -> list[ProbeResult]:
    rows = history.get("nodes", {})
    chosen: list[ProbeResult] = []
    chosen_ids: set[str] = set()
    endpoint_counts: Counter[str] = Counter()
    network_counts: Counter[str] = Counter()

    def add(item: ProbeResult) -> bool:
        network = network_key(item.endpoint_key)
        if item.node.node_id in chosen_ids or endpoint_counts[item.endpoint_key] >= 2:
            return False
        if network_counts[network] >= max_per_subnet:
            return False
        chosen.append(item)
        chosen_ids.add(item.node.node_id)
        endpoint_counts[item.endpoint_key] += 1
        network_counts[network] += 1
        return True

    for category, quota in category_quotas.items():
        wanted = max(quota * 3, quota + 2)
        category_items = [item for item in probes if item.node.category == category]
        groups: dict[str, list[ProbeResult]] = {"classic": [], "hysteria2": []}
        for item in category_items:
            groups["hysteria2" if item.node.is_hysteria else "classic"].append(item)
        for group in groups.values():
            group.sort(key=_rank_key(rows, preferred_countries))
        count = 0
        # Чередуем протокольные группы: Hysteria2 гарантированно получает долю проверок.
        while count < wanted and any(groups.values()):
            for group_name in ("classic", "hysteria2"):
                if count >= wanted:
                    break
                while groups[group_name]:
                    candidate = groups[group_name].pop(0)
                    if add(candidate):
                        count += 1
                        break
    maximum = max(target_count * 3, target_count + 6)
    rest = sorted(probes, key=_rank_key(rows, preferred_countries))
    for item in rest:
        if len(chosen) >= maximum:
            break
        add(item)
    return chosen


def quality_score(
    result: CheckResult, history: dict[str, Any], preferred_countries: tuple[str, ...]
) -> float:
    row = history.get("nodes", {}).get(result.node.node_id, {})
    successes = float(row.get("successes", 0))
    failures = float(row.get("failures", 0))
    streak = float(row.get("streak", 0))
    current_check = 30.0
    reliability = ((successes + 1) / (successes + failures + 2)) * 20
    stability = min(streak, 10) * 1.5
    try:
        country_index = preferred_countries.index(result.country)
        geography = max(2.0, 15.0 - country_index)
    except ValueError:
        geography = 1.0 if result.country != "XX" else 0.0
    latency = max(0.0, 10.0 * (1 - min(result.http_ms, 1500) / 1500))
    throughput = min(result.speed_mbps / 20.0, 1.0) * 7
    security = 3.0 if result.node.security in {"tls", "reality"} else 0.0
    protocol_bonus = _PROTOCOL_BONUS.get(result.node.transport, 0.0)
    compatibility = _TRANSPORT_SCORES.get(result.node.transport, 0.0)
    return round(
        min(
            100.0,
            current_check
            + reliability
            + stability
            + geography
            + latency
            + throughput
            + security
            + protocol_bonus
            + compatibility,
        ),
        1,
    )


def select_final(
    results: list[CheckResult],
    *,
    history: dict[str, Any],
    preferred_countries: tuple[str, ...],
    category_quotas: dict[str, int],
    target_count: int,
    max_per_endpoint: int,
    country_limits: dict[str, int] | None = None,
    max_per_subnet: int = 2,
) -> list[CheckResult]:
    scored = [
        CheckResult(
            item.node,
            item.tcp_ms,
            item.http_ms,
            item.speed_mbps,
            item.country,
            item.checked_at,
            quality_score(item, history, preferred_countries),
            item.resolved_ip,
            item.checks_passed,
        )
        for item in results
    ]
    scored.sort(
        key=lambda item: (
            is_historically_unreliable(item, history),
            -item.score,
            item.http_ms,
            item.node.node_id,
        )
    )
    selected: list[CheckResult] = []
    selected_ids: set[str] = set()
    endpoint_counts: Counter[str] = Counter()
    network_counts: Counter[str] = Counter()
    selected_countries: Counter[str] = Counter()
    country_limits = {code.upper(): limit for code, limit in (country_limits or {}).items()}

    def add(item: CheckResult) -> bool:
        country = item.country.upper()
        network = network_key(item.endpoint_key)
        if (
            item.node.node_id in selected_ids
            or endpoint_counts[item.endpoint_key] >= max_per_endpoint
            or (max_per_subnet and network_counts[network] >= max_per_subnet)
            or (
                country in country_limits
                and selected_countries[country] >= country_limits[country]
            )
        ):
            return False
        selected_countries[country] += 1
        selected.append(item)
        selected_ids.add(item.node.node_id)
        endpoint_counts[item.endpoint_key] += 1
        network_counts[network] += 1
        return True

    for category, quota in category_quotas.items():
        count = 0
        for item in scored:
            if count >= quota:
                break
            if item.node.category == category and add(item):
                count += 1
    for item in scored:
        if len(selected) >= target_count:
            break
        add(item)
    return selected[:target_count]

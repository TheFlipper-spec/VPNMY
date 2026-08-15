from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import BuildConfig
from .fetcher import fetch_all
from .history import load_history, prune_history, record_failure, record_success
from .models import CheckResult, Node
from .parser import ParseError, deduplicate, parse_source
from .probe import probe_all
from .publisher import atomic_publish, build_payloads, load_country_names
from .selector import infer_country, sample_candidates, select_final, shortlist
from .xray import resolve_xray, verify_all

LOGGER = logging.getLogger(__name__)


class BuildError(RuntimeError):
    """Сборка не может безопасно заменить последнюю рабочую подписку."""


@dataclass(frozen=True, slots=True)
class BuildReport:
    sources_ok: int
    sources_total: int
    parsed: int
    probed: int
    verified: int
    published: int
    status: str
    check_mode: str


def build_subscription(
    config: BuildConfig,
    *,
    skip_deep_check: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> BuildReport:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    xray_bin = None if skip_deep_check else resolve_xray(config.xray_bin)
    history = load_history(config.paths.history)
    fetch_results = fetch_all(config.sources, config.source_timeout_seconds, config.fetch_workers)
    source_stats: list[dict[str, Any]] = []
    all_nodes: list[Node] = []
    sources_ok = 0
    for fetched in fetch_results:
        row: dict[str, Any] = {
            "id": fetched.source.source_id,
            "name": fetched.source.name,
            "category": fetched.source.category,
            "available": fetched.ok,
            "fetch_ms": fetched.elapsed_ms,
            "found": 0,
            "accepted": 0,
            "rejected": 0,
        }
        if fetched.ok and fetched.text is not None:
            try:
                nodes, rejected = parse_source(fetched.text, fetched.source)
            except ParseError as exc:
                LOGGER.warning("Источник «%s» не разобран: %s", fetched.source.name, exc)
                row["available"] = False
                row["error"] = "parse_error"
            else:
                sources_ok += 1
                all_nodes.extend(nodes)
                row["accepted"] = len(nodes)
                row["rejected"] = rejected
                row["found"] = len(nodes) + rejected
                LOGGER.info(
                    "Источник «%s»: принято %d, отклонено %d",
                    fetched.source.name,
                    len(nodes),
                    rejected,
                )
        else:
            row["error"] = "fetch_error"
        source_stats.append(row)
    if sources_ok == 0:
        raise BuildError("ни один источник не доступен; последняя подписка сохранена без изменений")
    nodes = deduplicate(all_nodes)
    if not nodes:
        raise BuildError("источники не содержат валидных конфигураций")
    LOGGER.info("После дедупликации: %d конфигураций", len(nodes))
    candidates = sample_candidates(nodes, history, limit=config.max_candidates, now=now)
    probes = probe_all(candidates, config.tcp_timeout_seconds, config.probe_workers)
    if not probes:
        raise BuildError("ни один сервер не прошёл TCP-проверку")
    reachable_ids = {probe.node.node_id for probe in probes}
    tcp_failed = [node for node in candidates if node.node_id not in reachable_ids]
    probes_for_check = shortlist(
        probes, history, config.category_quotas, config.target_count, config.preferred_countries
    )
    checked_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    if skip_deep_check:
        checked = []
        for probe in probes_for_check:
            old = history.get("nodes", {}).get(probe.node.node_id, {})
            checked.append(
                CheckResult(
                    probe.node,
                    probe.tcp_ms,
                    probe.tcp_ms,
                    float(old.get("speed_mbps", 0)),
                    str(old.get("country") or infer_country(probe.node)),
                    checked_at,
                    resolved_ip=probe.resolved_ip,
                )
            )
        failed: list[Node] = []
        check_mode = "tcp_only"
        LOGGER.warning(
            "Глубокая проверка отключена: результат нельзя считать проверенным через VPN-туннель"
        )
    else:
        assert xray_bin is not None
        checked, failed = verify_all(
            probes_for_check,
            xray_bin=xray_bin,
            timeout=config.verify_timeout_seconds,
            speed_test_bytes=config.speed_test_bytes,
            workers=config.verify_workers,
        )
        unconfirmed = [result for result in checked if result.checks_passed < 2]
        if unconfirmed:
            LOGGER.warning("Отброшены узлы без двойного HTTPS-подтверждения: %d", len(unconfirmed))
            failed.extend(result.node for result in unconfirmed)
            checked = [result for result in checked if result.checks_passed >= 2]
        check_mode = "xray"
    if check_mode == "xray":
        for result in checked:
            record_success(history, result)
        for node in [*tcp_failed, *failed]:
            record_failure(history, node, checked_at)
    selected = select_final(
        checked,
        history=history,
        preferred_countries=config.preferred_countries,
        category_quotas=config.category_quotas,
        target_count=config.target_count,
        max_per_endpoint=config.max_per_endpoint,
    )
    if len(selected) < config.min_publish_count:
        raise BuildError(
            f"работают только {len(selected)} узлов (минимум {config.min_publish_count}); последняя подписка сохранена без изменений"
        )
    prune_history(history, now)
    payloads = build_payloads(
        selected,
        config=config,
        countries=load_country_names(config.paths.countries),
        history=history,
        source_stats=source_stats,
        generated_at=now,
        check_mode=check_mode,
    )
    if not dry_run:
        atomic_publish(payloads)
        LOGGER.info("Подписка атомарно обновлена: %d узлов", len(selected))
    else:
        LOGGER.info("Dry-run завершён: файлы не изменены")
    status = (
        "diagnostic"
        if check_mode != "xray"
        else ("healthy" if len(selected) >= config.target_count else "degraded")
    )
    return BuildReport(
        sources_ok,
        len(fetch_results),
        len(nodes),
        len(probes),
        len(checked),
        len(selected),
        status,
        check_mode,
    )

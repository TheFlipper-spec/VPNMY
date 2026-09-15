from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import BuildConfig
from .fetcher import fetch_all
from .history import load_history, prune_history, record_failure, record_success
from .hysteria import resolve_hysteria
from .models import CheckResult, Node
from .parser import ParseError, deduplicate, parse_source
from .probe import probe_all
from .publisher import atomic_publish, build_payloads, load_country_names
from .selector import (
    cap_per_source,
    infer_country,
    is_historically_unreliable,
    is_publication_stable,
    sample_candidates,
    select_final,
    shortlist,
)
from .source_health import (
    is_quarantined,
    load_health,
    prune_missing,
    public_row,
    record_run,
)
from .verifier import verify_all
from .xray import resolve_xray

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
    quarantined: int = 0
    skipped: int = 0


def _select(
    candidates: list[CheckResult],
    config: BuildConfig,
    history: dict[str, Any],
) -> list:
    return select_final(
        candidates,
        history=history,
        preferred_countries=config.preferred_countries,
        category_quotas=config.category_quotas,
        target_count=config.target_count,
        max_per_endpoint=config.max_per_endpoint,
        country_limits=config.country_limits,
        max_per_subnet=config.max_per_subnet,
    )


def build_subscription(
    config: BuildConfig,
    *,
    skip_deep_check: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> BuildReport:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    checked_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    if skip_deep_check:
        xray_bin = None
        hysteria_bin = None
        LOGGER.warning("Глубокая проверка отключена: клиенты Xray/Hysteria не запускаются")
    else:
        xray_bin = resolve_xray(config.xray_bin)
        hysteria_bin = resolve_hysteria(config.hysteria_bin)
        if hysteria_bin is None:
            LOGGER.warning(
                "Клиент Hysteria не найден (%s); hysteria2-узлы будут пропущены", config.hysteria_bin
            )
    history = load_history(config.paths.history)
    health = load_health(config.paths.source_health)
    fetch_results = fetch_all(
        config.sources, config.source_timeout_seconds, config.fetch_workers
    )
    source_stats: list[dict[str, Any]] = []
    all_nodes: list[Node] = []
    sources_ok = 0
    quarantined_count = 0
    enabled_total = sum(1 for source in config.sources if source.enabled)
    for fetched in fetch_results:
        source = fetched.source
        row: dict[str, Any] = {
            "id": source.source_id,
            "name": source.name,
            "category": source.category,
            "enabled": source.enabled,
            "available": False,
            "fetch_ms": fetched.elapsed_ms,
            "found": 0,
            "accepted": 0,
            "rejected": 0,
        }
        accepted_nodes: list[Node] = []
        rejected = 0
        error: str | None = None
        if fetched.ok and fetched.text is not None:
            try:
                accepted_nodes, rejected = parse_source(fetched.text, source)
            except ParseError as exc:
                LOGGER.warning("Источник «%s» не разобран: %s", source.name, exc)
                error = "parse_error"
        else:
            error = "fetch_error"
        healthy = record_run(
            health,
            source,
            ok=error is None,
            accepted=len(accepted_nodes),
            error=error,
            checked_at=checked_at,
            fail_threshold=config.source_fail_threshold,
        )
        in_quarantine = is_quarantined(health, source.source_id, config.source_fail_threshold)
        row.update(
            {
                "found": len(accepted_nodes) + rejected,
                "accepted": len(accepted_nodes),
                "rejected": rejected,
                "quarantined": in_quarantine,
                **{
                    key: value
                    for key, value in public_row(healthy).items()
                    if key not in {"last_attempt", "last_accepted"}
                },
            }
        )
        if error:
            row["error"] = error
        elif len(accepted_nodes) == 0:
            row["error"] = "empty"
        if in_quarantine:
            quarantined_count += 1
            LOGGER.info("Источник «%s» в карантине — его узлы не участвуют в отборе", source.name)
        else:
            all_nodes.extend(accepted_nodes)
            if error is None and accepted_nodes:
                sources_ok += 1
                row["available"] = True
                LOGGER.info(
                    "Источник «%s»: принято %d, отклонено %d",
                    source.name,
                    len(accepted_nodes),
                    rejected,
                )
            elif error is None:
                LOGGER.warning("Источник «%s» не отдал ни одной конфигурации", source.name)
        source_stats.append(row)
    prune_missing(health, list(config.sources))
    if sources_ok == 0:
        raise BuildError(
            "ни один источник не доступен или пуст; последняя подписка сохранена без изменений"
        )
    parsed_raw = deduplicate(all_nodes)
    capped = cap_per_source(
        parsed_raw, config.max_nodes_per_source, history, now
    )
    nodes = deduplicate(capped)
    if not nodes:
        raise BuildError("источники не содержат валидных конфигураций")
    LOGGER.info(
        "После дедупликации: %d конфигураций; после лимита на источник: %d",
        len(parsed_raw),
        len(nodes),
    )
    candidates = sample_candidates(nodes, history, limit=config.max_candidates, now=now)
    probes = probe_all(
        candidates,
        config.tcp_timeout_seconds,
        config.udp_timeout_seconds,
        config.probe_workers,
    )
    if not probes:
        raise BuildError("ни один сервер не прошёл сетевую предпроверку")
    reachable_ids = {probe.node.node_id for probe in probes}
    tcp_failed = [node for node in candidates if node.node_id not in reachable_ids]
    probes_for_check = shortlist(
        probes,
        history,
        config.category_quotas,
        config.target_count,
        config.preferred_countries,
        max_per_subnet=max(2, config.max_per_subnet),
    )
    skipped: list[Node] = []
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
        checked, failed, skipped = verify_all(
            probes_for_check,
            xray_bin=xray_bin,
            hysteria_bin=hysteria_bin,
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
    reliable = [item for item in checked if not is_historically_unreliable(item, history)]
    LOGGER.info(
        "После отсева нестабильных узлов: %d из %d прошли порог надёжности",
        len(reliable),
        len(checked),
    )
    if check_mode == "xray":
        stable = [
            item
            for item in reliable
            if is_publication_stable(item, history, config.stable_streak_required)
        ]
        if stable:
            pool = stable
            LOGGER.info(
                "Стабильных узлов (серия успешных проверок ≥ %d): %d",
                config.stable_streak_required,
                len(stable),
            )
        else:
            pool = reliable
            LOGGER.warning(
                "Узлов с требуемой серией стабильности нет — берём надёжные по факту этой проверки"
            )
    else:
        pool = reliable
    selected = _select(pool, config, history)
    if len(selected) < config.min_publish_count and len(pool) != len(checked):
        LOGGER.warning(
            "Стабильных/надёжных узлов мало (%d), добавляем все подтверждённые ядром узлы",
            len(selected),
        )
        selected = _select(checked, config, history)
    if len(selected) < config.min_publish_count:
        raise BuildError(
            f"работают только {len(selected)} узлов (минимум {config.min_publish_count}); "
            "последняя подписка сохранена без изменений"
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
        source_health=health,
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
        enabled_total,
        len(nodes),
        len(probes),
        len(checked),
        len(selected),
        status,
        check_mode,
        quarantined=quarantined_count,
        skipped=len(skipped),
    )

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import asn as asn_module
from . import globalping
from .config import BuildConfig
from .fetcher import fetch_all
from .history import load_history, prune_history, record_failure, record_skip, record_success
from .hysteria import resolve_hysteria
from .models import CheckResult, Node
from .parser import ParseError, deduplicate, parse_source
from .probe import probe_all
from .publisher import atomic_publish, build_payloads, load_country_names
from .selector import (
    cap_per_source,
    compute_diversity_stats,
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
    ru_summary: str = ""


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
        max_per_country=config.max_per_country,
        max_per_asn=config.max_per_asn,
        max_per_ip=config.max_per_ip,
        verify_median_threshold_ms=config.verify_median_threshold_ms,
    )


def _enrich_asn(results: list[CheckResult]) -> tuple[list[CheckResult], dict[str, Any]]:
    """Обогащает результаты ASN по IP сервера.

    Возвращает (обогащённые результаты, статистика). Не отправляет секреты,
    только IP. Ошибка обогащения не ломает сборку; неизвестные ASN остаются пустыми
    и не объединяются в один провайдер (лимит ASN их пропускает).
    """
    if not results:
        return results, {"enriched": 0, "failed": 0, "total": 0, "status": "skipped"}
    ip_to_asn: dict[str, str] = {}
    # Собираем уникальные IP серверов
    for r in results:
        ip = (r.resolved_ip or "").strip()
        if ip and ip not in ip_to_asn:
            ip_to_asn[ip] = (r.asn or "").strip()
    total = len(ip_to_asn)
    # Обогащаем только пустые
    enriched_before = sum(1 for v in ip_to_asn.values() if v)
    try:
        ip_to_asn = asn_module.enrich_asns(ip_to_asn)
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("ASN обогащение недоступно: %s", exc)
        return results, {"enriched": enriched_before, "failed": total - enriched_before, "total": total, "status": "error"}
    enriched_after = sum(1 for v in ip_to_asn.values() if v)
    failed = total - enriched_after
    # Создаём новые CheckResult с ASN (frozen требует пересоздания)
    enriched_results: list[CheckResult] = []
    for r in results:
        ip = (r.resolved_ip or "").strip()
        asn = ip_to_asn.get(ip, "")
        if asn and asn != (r.asn or ""):
            enriched_results.append(
                CheckResult(
                    r.node,
                    r.tcp_ms,
                    r.http_ms,
                    r.speed_mbps,
                    r.country,
                    r.checked_at,
                    r.score,
                    r.resolved_ip,
                    r.checks_passed,
                    r.egress_ip,
                    asn,
                    r.http_max_ms,
                    r.jitter_ms,
                    r.attempts,
                    r.samples,
                )
            )
        else:
            enriched_results.append(r)
    status = "ok" if failed == 0 else ("partial" if enriched_after > enriched_before else "unavailable")
    stats = {"enriched": enriched_after - enriched_before, "cached": enriched_before, "failed": failed, "total": total, "status": status}
    return enriched_results, stats


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
    # Оценка времени: 12 минут лимит. Посчитаем верхнюю оценку.
    # Probe: candidates до max_candidates (480) * (tcp 1.5 + udp 1.5) / workers 64 ~ 11 сек.
    # Verify: shortlist до target*3 (36-40) * attempts 3 * timeout 8 сек / workers 6 ~ 3 мин + speed 0.5 мин.
    # ASN: до 40 IP * 3 сек /5 workers ~ 24 сек.
    # Итого <5 мин с запасом.
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

    # --- Второй этап фильтрации: доступность из российской сети (Globalping, RU) ---
    # Локальная предпроверка идёт с GitHub-раннера (США/Европа) и не видит блокировки
    # ТСПУ. Перед дорогой глубокой проверкой отбрасываем узлы, подтверждённо недоступные
    # из РФ: это экономит лимиты ядер и не публикует «рабочие из США, мёртвые из РФ».
    # Приоритет российской проверки: опубликованные узлы → короткий список → остальные
    # по локальному пингу; всё в пределах бюджета ru_check_budget и свободной квоты API.
    prioritization = shortlist(
        probes,
        history,
        config.category_quotas,
        config.target_count,
        config.preferred_countries,
        max_per_subnet=max(2, config.max_per_subnet),
    )
    ru_results, ru_stats = globalping.run_ru_check(
        probes,
        prioritization,
        globalping.load_published_ids(config.paths.stats),
        config,
        checked_at=checked_at,
    )
    ru_blocked_ids: set[str] = set()
    for probe in probes:
        result = ru_results.get(probe.node.node_id)
        if result is None:
            continue
        if result.ok is not None or result.reason not in globalping.NOT_CHECKED_REASONS:
            globalping.record_ru_result(history, probe.node.node_id, result, checked_at)
        if result.ok is False:
            ru_blocked_ids.add(probe.node.node_id)
    if ru_blocked_ids:
        blocked_nodes = [p.node for p in probes if p.node.node_id in ru_blocked_ids]
        for node in blocked_nodes:
            record_failure(history, node, checked_at)
        LOGGER.warning(
            "Российская проверка (Globalping): %d узлов недоступны из РФ и исключены из проверки",
            len(blocked_nodes),
        )
    LOGGER.info(
        "Российская проверка (Globalping, RU): %s",
        globalping.format_summary(ru_stats),
    )
    probes_ru = [p for p in probes if p.node.node_id not in ru_blocked_ids]
    if not probes_ru:
        raise BuildError(
            "ни один сервер не доступен из российской сети; "
            "последняя подписка сохранена без изменений"
        )
    # Короткий список пересчитываем после RU-отсева, чтобы лимиты подсетей/эндпоинтов
    # заняли свободные места заменами, а не заблокированными узлами.
    probes_for_check = shortlist(
        probes_ru,
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
        asn_stats = {"status": "skipped", "total": 0}
    else:
        assert xray_bin is not None
        checked, failed, skipped = verify_all(
            probes_for_check,
            xray_bin=xray_bin,
            hysteria_bin=hysteria_bin,
            timeout=config.verify_timeout_seconds,
            speed_test_bytes=config.speed_test_bytes,
            workers=config.verify_workers,
            attempts=config.verify_measurements,
        )
        unconfirmed = [result for result in checked if result.checks_passed < 2]
        if unconfirmed:
            LOGGER.warning("Отброшены узлы без двойного HTTPS-подтверждения: %d", len(unconfirmed))
            failed.extend(result.node for result in unconfirmed)
            checked = [result for result in checked if result.checks_passed >= 2]
        check_mode = "xray"
        # ASN обогащение после проверки, до фильтрации качества
        checked, asn_stats = _enrich_asn(checked)
        LOGGER.info(
            "ASN обогащение: %s (всего IP: %d, обогащено: %d, неудач: %d)",
            asn_stats.get("status"),
            asn_stats.get("total", 0),
            asn_stats.get("enriched", 0),
            asn_stats.get("failed", 0),
        )
    if check_mode == "xray":
        for result in checked:
            record_success(history, result)
        for node in [*tcp_failed, *failed]:
            record_failure(history, node, checked_at)
        # Пропущенные из-за отсутствия ядра или бюджета — не считаются отказом
        for node in skipped:
            record_skip(history, node, checked_at)
        # Также узлы, которые были в capped/nodes но не попали в candidates/probes_for_check
        # из-за бюджета, не должны считаться проваленными — они просто не проверялись.
        # Но tcp_failed уже включает только кандидатов, не все. Узлы вне candidates — скип.
        not_checked_ids = {n.node_id for n in nodes} - {n.node_id for n in candidates} - {p.node.node_id for p in probes}
        # Для этих узлов фиксируем skip, чтобы не рос fail streak
        for nid in not_checked_ids:
            # найти узел
            node = next((n for n in nodes if n.node_id == nid), None)
            if node is not None:
                record_skip(history, node, checked_at)
    # Надёжные узлы: отсекаем хронически нестабильные (скользящее окно)
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

    # Диагностика разнообразия до финального отбора
    before_stats = compute_diversity_stats(pool) if pool else {}
    selected = _select(pool, config, history)
    excluded_by_filters = len(pool) - len(selected)
    # Более детальная диагностика: считаем, сколько отсеяно по каждой причине (приблизительно)
    # Для этого пробуем добавить узлы по одному и смотреть причину отказа — но проще логировать счётчики разнообразия.
    if len(selected) < config.min_publish_count and len(pool) != len(checked):
        LOGGER.warning(
            "Стабильных/надёжных узлов мало (%d), добавляем все подтверждённые ядром узлы",
            len(selected),
        )
        # Повторный отбор из всех проверенных с теми же лимитами, но без требования стабильности
        selected = _select(checked, config, history)
    if len(selected) < config.min_publish_count:
        raise BuildError(
            f"работают только {len(selected)} узлов (минимум {config.min_publish_count}); "
            "последняя подписка сохранена без изменений"
        )
    prune_history(history, now)
    # Дополнительная диагностика для publisher
    diversity_before = before_stats
    diversity_after = compute_diversity_stats(selected) if selected else {}
    # Сохраняем диагностику в историю комментов для stats.json через publisher
    # Передаём через source_stats extra?
    # Добавим в history временный ключ для publisher (не сохраняется на диск в stats, но используется)
    # Вместо этого вернём через глобальную переменную? Проще добавить в history["_diagnostics"]
    history["_diagnostics"] = {
        "diversity_before": diversity_before,
        "diversity_after": diversity_after,
        "excluded_count": excluded_by_filters,
        "asn": asn_stats if check_mode == "xray" else {"status": "skipped"},
        "median_threshold_ms": config.verify_median_threshold_ms,
        "verify_measurements": config.verify_measurements,
    }
    payloads = build_payloads(
        selected,
        config=config,
        countries=load_country_names(config.paths.countries),
        history=history,
        source_stats=source_stats,
        generated_at=now,
        check_mode=check_mode,
        source_health=health,
        ru_stats=ru_stats,
        ru_results=ru_results,
    )
    # Убираем временную диагностику из истории, чтобы не раздувать файл, но оставляем в stats через publisher
    history.pop("_diagnostics", None)
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
        ru_summary=globalping.format_summary(ru_stats),
    )

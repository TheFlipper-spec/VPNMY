"""Проверка доступности узлов из российских сетей через Globalping API.

Решаемая проблема: предпроверка с GitHub-раннера (США/Европа) не видит блокировки
ТСПУ в РФ. Этот модуль добавляет второй сигнал — TCP-проверку порта (классические
протоколы) или ICMP-пинг (Hysteria2) с российских узлов Globalping
(``locations: [{"country": "RU"}]``) до этапа глубокой проверки через туннель.

Принципы:
- Бюджет измерений ограничен (``ru_check_budget``) и дополнительно урезается
  фактической свободной квотой аккаунта (``GET /v1/limits``) — скрипт не должен
  расходовать платные кредиты.
- Одновременность ограничена ``asyncio.Semaphore`` (10–15 запросов).
- Ошибки 429 обрабатываются экспоненциальным откатом (exponential backoff)
  с джиттером и учётом ``Retry-After`` / «retry in N seconds».
- Общий дедлайн этапа (``ru_check_deadline_seconds``): при его истечении оставшиеся
  узлы помечаются как «не проверены» и сборка продолжает работу без российской
  точки — последняя рабочая подписка никогда не затирается из-за сбоя Globalping.
- Консервативные вердикты: «заблокировано в РФ» выносится только при подтверждении
  минимум двумя независимыми российскими проблами (TCP). Молчание ICMP для
  Hysteria2 — «неизвестно», а не «заблокировано» (ICMP часто гасят фаерволы).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .models import Node, ProbeResult

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.globalping.io"
TOKEN_ENV = "GLOBALPING_TOKEN"
RU_COUNTRY = "RU"
USER_AGENT = "FL1P-VPN-Subscription/2.4 (+https://github.com/TheFlipper-spec/VPNMY; ru-check)"
# Запас свободной квоты, который не трогаем, чтобы следующий запуск в том же
# часовом окне тоже успел выполнить российскую проверку.
QUOTA_RESERVE = 3
# Причины, означающие «измерение не выполнялось» (в отличие от «выполнено, но
# результат неоднозначен»).
NOT_CHECKED_REASONS = {"budget", "deadline", "quota_exhausted", "skipped"}
_RETRY_AFTER_RE = re.compile(r"retry in (\d+) seconds?", re.IGNORECASE)


class GlobalpingError(RuntimeError):
    """Невозможность получить результат от Globalping после всех повторных попыток."""


@dataclass(frozen=True, slots=True)
class RuProbeResult:
    """Вердикт российской точки для одного узла.

    ``ok``: True — доступен из РФ, False — заблокирован/недоступен,
    None — неизвестно (ошибка API, мало пробов, молчание ICMP и т.п.).
    """

    node_id: str
    ok: bool | None
    kind: str  # "tcp" | "icmp"
    latency_ms: int | None = None  # медиана RTT по успешным российским проблам
    probes_total: int = 0  # сколько российских пробов выполнило измерение
    probes_ok: int = 0  # сколько дали ответ
    reason: str = ""  # короткая причина (для ok=None или диагностики)


@dataclass(slots=True)
class RuCheckStats:
    """Сводка прогона российской проверки — публикуется в stats.json."""

    enabled: bool = False
    reason: str = ""  # почему этап пропущен (если enabled=False)
    configured_budget: int = 0
    budget: int = 0  # эффективный бюджет с учётом квоты API
    quota_remaining: int | None = None  # свободная квота на создание измерений
    probes_per_target: int = 0
    submitted: int = 0  # создано измерений
    checked: int = 0  # получены результаты
    reachable: int = 0
    blocked: int = 0
    unknown: int = 0
    not_checked: int = 0  # не проверялись (бюджет/дедлайн/квота)
    no_probes: int = 0  # API: нет доступных RU-пробов
    api_errors: int = 0  # необратимые ошибки API/сети
    rate_limited: int = 0  # количество ответов 429
    retries: int = 0  # повторные попытки после сбоев
    credits_seen: int = 0  # списанные кредиты (тревога: не должно быть > 0)
    started_at: str = ""
    elapsed_seconds: float = 0.0
    median_latency_ms: int | None = None

    def as_stats_dict(self) -> dict[str, Any]:
        return {
            "method": "globalping",
            "location": RU_COUNTRY,
            "enabled": self.enabled,
            "reason": self.reason or None,
            "configured_budget": self.configured_budget,
            "budget": self.budget,
            "quota_remaining": self.quota_remaining,
            "probes_per_target": self.probes_per_target,
            "submitted": self.submitted,
            "checked": self.checked,
            "reachable": self.reachable,
            "blocked": self.blocked,
            "unknown": self.unknown,
            "not_checked": self.not_checked,
            "no_ru_probes": self.no_probes,
            "api_errors": self.api_errors,
            "rate_limited": self.rate_limited,
            "retries": self.retries,
            "credits_consumed": self.credits_seen,
            "median_latency_ms": self.median_latency_ms,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "checked_at": self.started_at or None,
            "description": (
                "TCP-проверка порта (классические протоколы) и ICMP-пинг (Hysteria2) "
                "с российских узлов Globalping до глубокой проверки. «Заблокировано» — "
                "минимум два независимых RU-проба не подключились. Молчание ICMP для "
                "Hysteria2 считается «неизвестно», а не отказом. Проверка из российских "
                "дата-центров — не эквивалент домашней/мобильной сети РФ."
            ),
        }


def skipped_stats(reason: str) -> RuCheckStats:
    return RuCheckStats(enabled=False, reason=reason)


def _import_aiohttp() -> Any:
    try:
        import aiohttp
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise GlobalpingError(
            "aiohttp не установлен (нужен для российской проверки; см. requirements.txt)"
        ) from exc
    return aiohttp


def _kind_of(probe: ProbeResult) -> str:
    return "icmp" if probe.node.is_hysteria else "tcp"


def is_enabled(config: Any) -> tuple[bool, str]:
    """Этап включён, если не выключен конфигурацией и задан токен."""
    if config.ru_check_enabled is False:
        return False, "отключено в конфигурации (ru_check_enabled: false)"
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        return False, f"нет токена: переменная окружения {TOKEN_ENV} не задана"
    try:
        _import_aiohttp()
    except GlobalpingError as exc:
        return False, str(exc)
    return True, ""


def load_published_ids(stats_path: Any) -> set[str]:
    """ID узлов текущей опубликованной подписки — они пере-проверяются в первую очередь."""
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return set()
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, list):
        return set()
    return {
        row["id"]
        for row in servers
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def order_for_check(
    probes: Sequence[ProbeResult],
    shortlisted: Sequence[ProbeResult] | None = None,
    published_ids: Mapping[str, Any] | Sequence[str] | set[str] | frozenset[str] = frozenset(),
) -> list[ProbeResult]:
    """Порядок российской проверки: опубликованные → shortlist → остальные по локальному пингу."""
    published = set(published_ids or ())
    seen: set[str] = set()
    ordered: list[ProbeResult] = []

    def add(item: ProbeResult) -> None:
        if item.node.node_id in seen:
            return
        seen.add(item.node.node_id)
        ordered.append(item)

    by_local = sorted(probes, key=lambda p: (p.tcp_ms, p.node.node_id))
    for probe in by_local:
        if probe.node.node_id in published:
            add(probe)
    if shortlisted:
        for probe in shortlisted:
            add(probe)
    for probe in by_local:
        add(probe)
    return ordered


def parse_measurement(payload: Mapping[str, Any]) -> tuple[int, int, int | None, tuple[str, ...]]:
    """Разбирает результат измерения Globalping.

    Возвращает (число пробов, число успешных, медиана RTT в мс, страны пробов).
    """
    results = payload.get("results")
    if not isinstance(results, list):
        return 0, 0, None, ()
    total = 0
    ok = 0
    latencies: list[float] = []
    countries: list[str] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        probe_meta = row.get("probe")
        probe_meta = probe_meta if isinstance(probe_meta, dict) else {}
        country = str(probe_meta.get("country") or "")
        if country:
            countries.append(country)
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        total += 1
        values = _extract_rtts(result)
        if values:
            ok += 1
            latencies.extend(values)
    latency_ms = int(round(statistics.median(latencies))) if latencies else None
    return total, ok, latency_ms, tuple(sorted(set(countries)))


def _extract_rtts(result: Mapping[str, Any]) -> list[float]:
    """Извлекает RTT из результата проба: сначала timings, затем сводные stats."""
    values: list[float] = []
    timings = result.get("timings")
    if isinstance(timings, list):
        for item in timings:
            rtt = item.get("rtt") if isinstance(item, dict) else item
            value = _as_float(rtt)
            if value is not None and value >= 0:
                values.append(value)
    if values:
        return values
    stats = result.get("stats")
    if isinstance(stats, dict):
        received = _as_float(stats.get("rcv")) or 0
        loss = _as_float(stats.get("loss"))
        if received > 0 and (loss is None or loss < 100):
            avg = _as_float(stats.get("avg"))
            if avg is not None:
                values.append(avg)
    return values


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # защита от NaN


def decide_verdict(kind: str, probes_total: int, probes_ok: int) -> tuple[bool | None, str]:
    """Консервативный вердикт по итогам российского измерения."""
    if probes_ok > 0:
        return True, ""
    if probes_total >= 2:
        if kind == "tcp":
            # Минимум два независимых RU-проба не смогли подключиться.
            return False, "blocked"
        # ICMP часто гасят фаерволы, даже когда сервис работает:
        # для Hysteria2 молчание — «неизвестно», а не «заблокировано».
        return None, "icmp_silent"
    if probes_total == 1:
        return None, "single_probe_failed"
    return None, "no_results"


def record_ru_result(
    history: dict[str, Any], node_id: str, result: RuProbeResult, checked_at: str
) -> None:
    """Фиксирует российский вердикт в истории узла (не трогая окно надёжности)."""
    rows = history.setdefault("nodes", {})
    row = rows.get(node_id)
    if not isinstance(row, dict):
        row = {}
        rows[node_id] = row
    if result.ok is True:
        row["ru_ms"] = result.latency_ms
        row["ru_ok_at"] = checked_at
        row["ru_blocked_streak"] = 0
    elif result.ok is False:
        row["ru_blocked"] = True
        row["ru_blocked_at"] = checked_at
        row["ru_blocked_streak"] = int(row.get("ru_blocked_streak", 0) or 0) + 1
        row["ru_ms"] = None
    else:
        row["ru_unknown_at"] = checked_at


def run_async(coro: Any) -> Any:
    """Запускает корутину из синхронного кода; устойчива к уже работающему циклу."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="globalping") as pool:
        return pool.submit(asyncio.run, coro).result()


def format_summary(stats: RuCheckStats) -> str:
    """Однострочная сводка для логов и Job Summary."""
    if not stats.enabled:
        return f"пропущена: {stats.reason}"
    median = (
        f"{stats.median_latency_ms} мс" if stats.median_latency_ms is not None else "н/д"
    )
    return (
        f"проверено {stats.checked} (доступно {stats.reachable}, заблокировано {stats.blocked}, "
        f"неизвестно {stats.unknown}, не проверено {stats.not_checked}; "
        f"429: {stats.rate_limited}, повторов: {stats.retries}); "
        f"бюджет {stats.budget}/{stats.configured_budget}; медиана RU-задержки {median}; "
        f"{stats.elapsed_seconds:.1f} с"
    )


def run_ru_check(
    probes: Sequence[ProbeResult],
    shortlisted: Sequence[ProbeResult] | None,
    published_ids: set[str] | frozenset[str],
    config: Any,
    *,
    checked_at: str,
) -> tuple[dict[str, RuProbeResult], RuCheckStats]:
    """Синхронный фасад: проверяет кандидатов из российских узлов Globalping.

    Если этап отключён (нет токена/конфигурация) — быстро возвращает пустой
    результат и причину пропуска, не трогая сеть.
    """
    enabled, reason = is_enabled(config)
    if not enabled:
        LOGGER.info("Российская проверка (Globalping) пропущена: %s", reason)
        return {}, skipped_stats(reason)
    ordered = order_for_check(probes, shortlisted, published_ids)
    token = os.environ.get(TOKEN_ENV, "").strip()
    started = time.monotonic()
    LOGGER.info(
        "Российская проверка (Globalping, %s): кандидатов %d, бюджет %d, параллельность %d",
        RU_COUNTRY,
        len(ordered),
        config.ru_check_budget,
        config.ru_check_concurrency,
    )
    results, stats = run_async(
        _run(
            ordered,
            token=token,
            checked_at=checked_at,
            budget=config.ru_check_budget,
            concurrency=config.ru_check_concurrency,
            probes_per_target=config.ru_check_probes,
            packets=config.ru_check_packets,
            poll_interval=config.ru_check_poll_seconds,
            deadline_seconds=config.ru_check_deadline_seconds,
        )
    )
    stats.elapsed_seconds = time.monotonic() - started
    return results, stats


class GlobalpingClient:
    """Асинхронный клиент Globalping API с лимитами и повторными попытками."""

    def __init__(
        self,
        token: str,
        session: Any,
        stats: RuCheckStats,
        *,
        base_url: str = DEFAULT_BASE_URL,
        probes_per_target: int = 3,
        packets: int = 2,
        poll_interval: float = 0.7,
        deadline_seconds: float = 420.0,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        create_retries: int = 4,
        poll_retries: int = 6,
    ) -> None:
        self._token = token
        self._session = session
        self._stats = stats
        self._base_url = base_url.rstrip("/")
        self._probes_per_target = probes_per_target
        self._packets = packets
        self._poll_interval = max(0.5, poll_interval)  # API: не чаще 2 запросов/с на измерение
        self._deadline_seconds = deadline_seconds
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._create_retries = create_retries
        self._poll_retries = poll_retries
        self._quota_remaining: int | None = None

    @property
    def quota_remaining(self) -> int | None:
        return self._quota_remaining

    def _jittered(self, base: float) -> float:
        return base * (0.5 + random.random() / 2)

    def _backoff_delay(self, attempt: int) -> float:
        base = min(self._backoff_base * (2**attempt), self._backoff_cap)
        return self._jittered(base)

    @staticmethod
    def _retry_after(headers: Mapping[str, Any], payload: Mapping[str, Any]) -> float | None:
        header = str(headers.get("Retry-After") or "").strip()
        if header:
            value = _as_float(header)
            if value is not None and value >= 0:
                return min(value, 60.0)
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str):
            match = _RETRY_AFTER_RE.search(message)
            if match:
                return min(float(match.group(1)), 60.0)
        return None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        retries: int,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        """HTTP-запрос с повторами: 429 (backoff + Retry-After), 5xx, сетевые сбои."""
        attempt = 0
        while True:
            try:
                async with self._session.request(method, url, json=json_body) as response:
                    text = await response.text(errors="replace")
                    try:
                        payload = json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        payload = {"raw": text}
                    headers = {str(k): str(v) for k, v in response.headers.items()}
                    status = int(response.status)
                    if status == 429:
                        self._stats.rate_limited += 1
                        self._stats.retries += 1
                        if attempt >= retries:
                            raise GlobalpingError("лимит запросов Globalping (429) не снят")
                        wait = self._retry_after(headers, payload)
                        wait = self._backoff_delay(attempt) if wait is None else wait
                        LOGGER.warning(
                            "Globalping 429: пауза %.1f с (попытка %d/%d) для %s %s",
                            wait,
                            attempt + 1,
                            retries + 1,
                            method,
                            url,
                        )
                        await asyncio.sleep(max(0.5, min(wait, 60.0)))
                        attempt += 1
                        continue
                    if 500 <= status < 600:
                        self._stats.retries += 1
                        if attempt >= retries:
                            raise GlobalpingError(f"ошибка сервера Globalping: HTTP {status}")
                        await asyncio.sleep(self._backoff_delay(attempt))
                        attempt += 1
                        continue
                    return status, payload, headers
            except GlobalpingError:
                raise
            except Exception as exc:
                # Сетевые сбои aiohttp (ClientConnectorError и т.п.), таймауты,
                # ошибки декомпрессии — все повторятся с экспоненциальным откатом.
                self._stats.retries += 1
                if attempt >= retries:
                    raise GlobalpingError(f"сбой запроса к Globalping: {exc}") from exc
                await asyncio.sleep(self._backoff_delay(attempt))
                attempt += 1

    async def update_quota(self) -> None:
        """Best-effort: свободная квота на создание измерений (не трогаем кредиты)."""
        try:
            status, payload, _headers = await self._request(
                "GET", f"{self._base_url}/v1/limits", retries=1
            )
        except GlobalpingError as exc:
            LOGGER.warning(
                "Globalping: квота недоступна (%s); работаю по заданному бюджету", exc
            )
            return
        if status != 200:
            return
        rate_limit = payload.get("rateLimit")
        measurements = rate_limit.get("measurements") if isinstance(rate_limit, dict) else None
        create = measurements.get("create") if isinstance(measurements, dict) else None
        if isinstance(create, dict) and create.get("type") == "user":
            remaining = create.get("remaining")
            if isinstance(remaining, int) and not isinstance(remaining, bool):
                self._quota_remaining = max(0, remaining)
                self._stats.quota_remaining = self._quota_remaining

    def _consume_quota(self, headers: Mapping[str, str]) -> None:
        if self._quota_remaining is not None:
            cost = headers.get("X-Request-Cost", "1")
            consumed = int(cost) if cost.isdigit() else 1
            self._quota_remaining = max(0, self._quota_remaining - consumed)
        credits = headers.get("X-Credits-Consumed", "")
        if credits.isdigit() and int(credits) > 0:
            self._stats.credits_seen += int(credits)
            self._quota_remaining = 0
            LOGGER.error(
                "Globalping начал списывать кредиты (%s) — создание измерений остановлено", credits
            )

    async def _create_measurement(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
        return await self._request(
            "POST",
            f"{self._base_url}/v1/measurements",
            json_body=body,
            retries=self._create_retries,
        )

    async def _poll_measurement(self, measurement_id: str, deadline: float) -> dict[str, Any] | None:
        url = f"{self._base_url}/v1/measurements/{measurement_id}"
        max_polls = max(8, int(self._deadline_seconds / self._poll_interval) + 5)
        polls = 0
        while True:
            if time.monotonic() >= deadline:
                return None
            try:
                status, payload, _headers = await self._request(
                    "GET", url, retries=self._poll_retries
                )
            except GlobalpingError as exc:
                LOGGER.warning("Globalping: опрос измерения %s не удался: %s", measurement_id, exc)
                return None
            if status == 404:
                return None
            state = str(payload.get("status") or "").lower()
            if state != "in-progress":
                return payload
            polls += 1
            if polls >= max_polls:
                return None
            # По рекомендации API: ждать не чаще, чем раз в 500 мс ПОСЛЕ получения ответа.
            await asyncio.sleep(self._poll_interval + random.uniform(0.0, 0.15))

    async def check_one(self, probe: ProbeResult, deadline: float) -> RuProbeResult:
        """Полный цикл для одного узла: создание измерения → опрос → вердикт."""
        node: Node = probe.node
        kind = _kind_of(probe)
        target = (probe.resolved_ip or node.host).strip()
        protocol = "ICMP" if kind == "icmp" else "TCP"
        options: dict[str, Any] = {"packets": self._packets, "protocol": protocol}
        if protocol == "TCP":
            options["port"] = node.probe_port
        body = {
            "type": "ping",
            "target": target,
            "locations": [{"country": RU_COUNTRY}],
            "limit": self._probes_per_target,
            "measurementOptions": options,
        }
        try:
            status, payload, headers = await self._create_measurement(body)
        except GlobalpingError as exc:
            LOGGER.warning("Globalping: не удалось создать измерение для %s: %s", target, exc)
            return RuProbeResult(node.node_id, None, kind, reason="api_error")
        if status == 422:
            # Российские пробы сейчас офлайн — не расцениваем как блокировку узла.
            self._stats.no_probes += 1
            return RuProbeResult(node.node_id, None, kind, reason="no_ru_probes")
        if status != 202:
            self._stats.api_errors += 1
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else str(error or payload)
            LOGGER.warning(
                "Globalping: создание измерения для %s отклонено (HTTP %s): %s",
                target,
                status,
                str(message)[:200],
            )
            return RuProbeResult(node.node_id, None, kind, reason="create_error")
        self._stats.submitted += 1
        self._consume_quota(headers)
        measurement_id = str(payload.get("id") or "")
        if not measurement_id:
            return RuProbeResult(node.node_id, None, kind, reason="create_error:no_id")
        result = await self._poll_measurement(measurement_id, deadline)
        if result is None:
            self._stats.api_errors += 1
            return RuProbeResult(node.node_id, None, kind, reason="poll_timeout")
        total, ok, latency_ms, countries = parse_measurement(result)
        verdict, reason = decide_verdict(kind, total, ok)
        if countries and RU_COUNTRY not in countries:
            LOGGER.warning(
                "Globalping: для %s ответили пробы стран %s (ожидалось %s)",
                target,
                ",".join(countries),
                RU_COUNTRY,
            )
        return RuProbeResult(
            node.node_id, verdict, kind, latency_ms, total, ok, reason
        )


async def _run(
    ordered: list[ProbeResult],
    *,
    token: str,
    checked_at: str,
    budget: int,
    concurrency: int,
    probes_per_target: int,
    packets: int,
    poll_interval: float,
    deadline_seconds: float,
) -> tuple[dict[str, RuProbeResult], RuCheckStats]:
    """Асинхронный прогон: квота → параллельные измерения в пределах дедлайна."""
    aiohttp = _import_aiohttp()
    stats = RuCheckStats(
        enabled=True,
        configured_budget=budget,
        probes_per_target=probes_per_target,
        started_at=checked_at,
    )
    results: dict[str, RuProbeResult] = {}
    if not ordered:
        return results, stats

    def not_checked(probe: ProbeResult, reason: str) -> RuProbeResult:
        return RuProbeResult(probe.node.node_id, None, _kind_of(probe), reason=reason)

    timeout = aiohttp.ClientTimeout(total=30.0, connect=8.0)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        client = GlobalpingClient(
            token,
            session,
            stats,
            probes_per_target=probes_per_target,
            packets=packets,
            poll_interval=poll_interval,
            deadline_seconds=deadline_seconds,
        )
        await client.update_quota()
        effective = budget
        if client.quota_remaining is not None:
            effective = min(budget, max(0, client.quota_remaining - QUOTA_RESERVE))
            if effective < budget:
                LOGGER.info(
                    "Globalping: свободная квота %d — бюджет снижен с %d до %d",
                    client.quota_remaining,
                    budget,
                    effective,
                )
        stats.budget = effective
        if effective <= 0:
            stats.reason = "свободная квота Globalping исчерпана (до резерва)"

        # Дедупликация по физическому endpoint: разные конфигурации одного
        # IP:port (и протокола) проверяются одним измерением, вердикт
        # распространяется на все — экономим бюджет API.
        groups: dict[str, list[ProbeResult]] = {}
        for probe in ordered:
            groups.setdefault(f"{_kind_of(probe)}:{probe.endpoint_key}", []).append(probe)
        representatives = [group[0] for group in groups.values()]  # порядок = приоритет

        semaphore = asyncio.Semaphore(max(1, concurrency))
        deadline = time.monotonic() + deadline_seconds

        async def work(representative: ProbeResult, group: list[ProbeResult]) -> None:
            async with semaphore:
                try:
                    if time.monotonic() >= deadline:
                        result = not_checked(representative, "deadline")
                    elif client.quota_remaining is not None and client.quota_remaining <= QUOTA_RESERVE:
                        result = not_checked(representative, "quota_exhausted")
                    else:
                        result = await client.check_one(representative, deadline)
                except Exception as exc:  # отдельный сбой не роняет весь прогон
                    LOGGER.warning(
                        "Globalping: неожиданный сбой для узла %s: %s",
                        representative.node.node_id,
                        exc,
                    )
                    stats.api_errors += 1
                    result = not_checked(representative, "unexpected")
                for probe in group:
                    results[probe.node.node_id] = result

        selected = representatives[:effective]
        tasks = [
            asyncio.create_task(work(rep, groups[f"{_kind_of(rep)}:{rep.endpoint_key}"]))
            for rep in selected
        ]
        tail_reason = "quota_exhausted" if effective <= 0 else "budget"
        for rep in representatives[effective:]:
            for probe in groups[f"{_kind_of(rep)}:{rep.endpoint_key}"]:
                results[probe.node.node_id] = not_checked(probe, tail_reason)
        if tasks:
            await asyncio.gather(*tasks)

    # Итоговые счётчики по фактическим вердиктам.
    # «Проверено» — только измерения, дошедшие до финального состояния;
    # ошибки создания/опроса уже учтены в api_errors/no_probes.
    finished_reasons = {"", "blocked", "icmp_silent", "single_probe_failed", "no_results"}
    latencies = [
        r.latency_ms for r in results.values() if r.ok is True and r.latency_ms is not None
    ]
    stats.median_latency_ms = int(round(statistics.median(latencies))) if latencies else None
    for result in results.values():
        if result.ok is True:
            stats.reachable += 1
        elif result.ok is False:
            stats.blocked += 1
        elif result.reason in NOT_CHECKED_REASONS or result.reason == "unexpected":
            stats.not_checked += 1
        elif result.reason in finished_reasons:
            stats.unknown += 1
    stats.checked = stats.reachable + stats.blocked + stats.unknown
    if stats.no_probes:
        stats.reason = "нет доступных российских пробов Globalping"
    elif stats.credits_seen:
        stats.reason = f"остановлено: API списало {stats.credits_seen} кредит(ов)"
    return results, stats

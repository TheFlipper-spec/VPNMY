from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import CheckResult, Node

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
# Размер скользящего окна для оценки надёжности (последние N циклов).
DEFAULT_RECENT_WINDOW = 10
# Максимальное число хранимых выборок задержки на узел (медианы последних проверок).
MAX_LATENCY_SAMPLES = 20


def empty_history() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "nodes": {}}


def _ensure_row(row: dict[str, Any]) -> dict[str, Any]:
    """Миграция старой записи к новому формату без потери полезных данных."""
    # successes/failures/streak/country и т.п. остаются как есть.
    # Добавляем новые поля по необходимости, не стирая старые.
    if "recent" not in row:
        # Попытка восстановить скользящее окно из накопленных счётчиков, но без выдумывания истории.
        # Если есть streak>0 — последние streak проверок успешны; иначе оставляем пустое окно,
        # чтобы будущие циклы наполнили его реальными результатами.
        streak = int(row.get("streak", 0) or 0)
        if streak > 0:
            recent = [1] * min(streak, DEFAULT_RECENT_WINDOW)
            # Если известно число неудач, можем добавить нули, но порядок неизвестен — не смешиваем.
            # Оставляем только успешную серию, иначе рискуем исказить окно.
            row["recent"] = recent
        else:
            # Для старых узлов без окна — начинаем с пустого, но сохраняем счётчики.
            row["recent"] = []
    else:
        # Защита от битого типа.
        if not isinstance(row.get("recent"), list):
            row["recent"] = []
        # Обрезать до окна.
        if len(row["recent"]) > DEFAULT_RECENT_WINDOW:
            row["recent"] = row["recent"][-DEFAULT_RECENT_WINDOW:]
    # Ограничить бесконечный рост дополнительных метрик, если они появились в будущих версиях.
    if "latency_medians" in row and isinstance(row["latency_medians"], list) and len(row["latency_medians"]) > MAX_LATENCY_SAMPLES:
        row["latency_medians"] = row["latency_medians"][-MAX_LATENCY_SAMPLES:]
    return row


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_history()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("nodes"), dict):
            raise ValueError("неподдерживаемая схема")
        # Миграция строк
        for node_id, row in list(data["nodes"].items()):
            if isinstance(row, dict):
                data["nodes"][node_id] = _ensure_row(row)
            else:
                data["nodes"].pop(node_id, None)
        return data
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning("История проверок повреждена и будет создана заново: %s", exc)
        return empty_history()


def _recent_success_rate(row: dict[str, Any]) -> float | None:
    recent = row.get("recent")
    if isinstance(recent, list) and recent:
        successes = sum(1 for v in recent if v)
        total = len(recent)
        return (successes + 1) / (total + 2)  # сглаживание как в старой формуле
    return None


def record_success(history: dict[str, Any], result: CheckResult) -> None:
    row = history["nodes"].setdefault(result.node.node_id, {})
    _ensure_row(row)
    row.update(
        {
            "successes": int(row.get("successes", 0)) + 1,
            "failures": int(row.get("failures", 0)),
            "streak": min(int(row.get("streak", 0)) + 1, 1000),
            "last_success": result.checked_at,
            "last_seen": result.checked_at,
            "country": result.country,
            "category": result.node.category,
            "tcp_ms": result.tcp_ms,
            "http_ms": result.http_ms,
            "http_max_ms": getattr(result, "http_max_ms", result.http_ms),
            "jitter_ms": getattr(result, "jitter_ms", 0),
            "speed_mbps": result.speed_mbps,
            "resolved_ip": result.resolved_ip,
            "egress_ip": getattr(result, "egress_ip", ""),
            "asn": getattr(result, "asn", ""),
            "checks_passed": result.checks_passed,
            "median_ms": result.http_ms,
        }
    )
    # Обновляем скользящее окно: успех = 1
    recent = row.get("recent", [])
    recent.append(1)
    if len(recent) > DEFAULT_RECENT_WINDOW:
        recent = recent[-DEFAULT_RECENT_WINDOW:]
    row["recent"] = recent
    # История медиан для диагностики (не раздуваем бесконечно)
    medians = row.get("latency_medians")
    if not isinstance(medians, list):
        medians = []
    medians.append(int(result.http_ms))
    if len(medians) > MAX_LATENCY_SAMPLES:
        medians = medians[-MAX_LATENCY_SAMPLES:]
    row["latency_medians"] = medians
    _ensure_row(row)


def record_failure(history: dict[str, Any], node: Node, checked_at: str) -> None:
    row = history["nodes"].setdefault(node.node_id, {})
    _ensure_row(row)
    row.update(
        {
            "successes": int(row.get("successes", 0)),
            "failures": int(row.get("failures", 0)) + 1,
            "streak": 0,
            "last_seen": checked_at,
            "category": node.category,
        }
    )
    recent = row.get("recent", [])
    recent.append(0)
    if len(recent) > DEFAULT_RECENT_WINDOW:
        recent = recent[-DEFAULT_RECENT_WINDOW:]
    row["recent"] = recent


def record_skip(history: dict[str, Any], node: Node, checked_at: str) -> None:
    """Пропуск из-за бюджета/отсутствия ядра/незапланированной проверки — не считается отказом.

    Обновляем только last_seen, не трогаем successes/failures/streak/recent.
    """
    row = history["nodes"].setdefault(node.node_id, {})
    _ensure_row(row)
    # Только фиксируем, что узел видели, но не меняем окно надёжности.
    row["last_seen"] = checked_at
    if "category" not in row:
        row["category"] = node.category
    # Не добавляем в recent, не сбрасываем streak.


def prune_history(
    history: dict[str, Any], now: datetime, *, keep_days: int = 30, max_nodes: int = 3000
) -> None:
    threshold = now.astimezone(UTC) - timedelta(days=keep_days)
    rows = history.get("nodes", {})

    def parsed_time(row: dict[str, Any]) -> datetime:
        try:
            value = datetime.fromisoformat(str(row.get("last_seen", "")).replace("Z", "+00:00"))
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)

    fresh = [
        (node_id, row, parsed_time(row)) for node_id, row in rows.items() if isinstance(row, dict)
    ]
    fresh = [item for item in fresh if item[2] >= threshold]
    fresh.sort(key=lambda item: item[2], reverse=True)
    history["nodes"] = {node_id: row for node_id, row, _ in fresh[:max_nodes]}
    history["schema_version"] = SCHEMA_VERSION

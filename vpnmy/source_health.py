"""История здоровья источников и автоматический карантин.

Источник, который несколько запусков подряд не загружается, не парсится
или отдаёт ноль валидных конфигураций, уходит в карантин: его узлы не
попадают в выборку, а состояние видно в stats.json и на странице статуса.
При первом же успешном запуске источник автоматически возвращается.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import Source

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1


def empty_health() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "sources": {}}


def load_health(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return empty_health()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("sources"), dict):
            raise ValueError("неподдерживаемая схема")
        return data
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning("История источников повреждена и будет создана заново: %s", exc)
        return empty_health()


def is_quarantined(health: dict[str, Any], source_id: str, fail_threshold: int) -> bool:
    row = health.get("sources", {}).get(source_id, {})
    if not isinstance(row, dict):
        return False
    return int(row.get("fail_streak", 0)) >= fail_threshold


def record_run(
    health: dict[str, Any],
    source: Source,
    *,
    ok: bool,
    accepted: int,
    error: str | None,
    checked_at: str,
    fail_threshold: int,
) -> dict[str, Any]:
    """Обновляет строку здоровья источника. Успех = загружен И дал конфиги."""
    sources = health.setdefault("sources", {})
    row = sources.setdefault(
        source.source_id,
        {
            "attempts": 0,
            "successes": 0,
            "fail_streak": 0,
            "accepted_total": 0,
            "last_accepted": 0,
            "quarantined": False,
        },
    )
    effective_ok = ok and accepted > 0
    row["attempts"] = int(row.get("attempts", 0)) + 1
    row["last_attempt"] = checked_at
    row["name"] = source.name
    if effective_ok:
        row["successes"] = int(row.get("successes", 0)) + 1
        row["fail_streak"] = 0
        row["last_ok"] = checked_at
        row["last_accepted"] = accepted
        row["accepted_total"] = int(row.get("accepted_total", 0)) + accepted
        row.pop("last_error", None)
        if row.get("quarantined"):
            LOGGER.info("Источник «%s» восстановлен и выведен из карантина", source.name)
        row["quarantined"] = False
    else:
        row["fail_streak"] = int(row.get("fail_streak", 0)) + 1
        row["last_accepted"] = accepted
        if error:
            row["last_error"] = error
        elif accepted == 0:
            row["last_error"] = "empty"
        was_quarantined = row.get("quarantined", False)
        row["quarantined"] = row["fail_streak"] >= fail_threshold
        if row["quarantined"] and not was_quarantined:
            LOGGER.warning(
                "Источник «%s» ушёл в карантин после %d неудачных запусков подряд",
                source.name,
                row["fail_streak"],
            )
    return row


def prune_missing(health: dict[str, Any], sources: list[Source]) -> None:
    known = {source.source_id for source in sources}
    health["sources"] = {
        source_id: row
        for source_id, row in health.get("sources", {}).items()
        if source_id in known
    }
    health["schema_version"] = SCHEMA_VERSION


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Версия строки для stats.json без лишних внутренних полей."""
    return {
        "attempts": int(row.get("attempts", 0)),
        "successes": int(row.get("successes", 0)),
        "fail_streak": int(row.get("fail_streak", 0)),
        "quarantined": bool(row.get("quarantined", False)),
        "last_ok": row.get("last_ok"),
        "last_attempt": row.get("last_attempt"),
        "last_accepted": int(row.get("last_accepted", 0)),
        "last_error": row.get("last_error"),
    }

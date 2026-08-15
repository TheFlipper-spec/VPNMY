from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import CheckResult, Node

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1


def empty_history() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "nodes": {}}


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_history()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("nodes"), dict):
            raise ValueError("неподдерживаемая схема")
        return data
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning("История проверок повреждена и будет создана заново: %s", exc)
        return empty_history()


def record_success(history: dict[str, Any], result: CheckResult) -> None:
    row = history["nodes"].setdefault(result.node.node_id, {})
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
            "speed_mbps": result.speed_mbps,
            "resolved_ip": result.resolved_ip,
            "checks_passed": result.checks_passed,
        }
    )


def record_failure(history: dict[str, Any], node: Node, checked_at: str) -> None:
    row = history["nodes"].setdefault(node.node_id, {})
    row.update(
        {
            "successes": int(row.get("successes", 0)),
            "failures": int(row.get("failures", 0)) + 1,
            "streak": 0,
            "last_seen": checked_at,
            "category": node.category,
        }
    )


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

from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import BuildConfig
from .models import CheckResult

MOSCOW = ZoneInfo("Europe/Moscow")
_CATEGORY_NAMES = {"universal": "Обычный интернет", "whitelist": "Белые списки"}


def country_flag(code: str) -> str:
    code = code.upper()
    if len(code) != 2 or not code.isalpha() or code == "XX":
        return "🌐"
    return "".join(chr(127397 + ord(char)) for char in code)


def load_country_names(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"не удалось загрузить справочник стран {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("справочник стран должен быть JSON-объектом")
    names: dict[str, str] = {}
    for code, label in data.items():
        if isinstance(code, str) and isinstance(label, str):
            names[code.upper()] = label.lstrip("🇦🇧🇨🇩🇪🇫🇬🇭🇮🇯🇰🇱🇲🇳🇴🇵🇶🇷🇸🇹🇺🇻🇼🇽🇾🇿 ")
    return names


def display_name(result: CheckResult, countries: dict[str, str]) -> str:
    country = countries.get(result.country, "Локация не определена")
    category = "Белые списки" if result.node.category == "whitelist" else "Интернет"
    return f"FL1P • {country_flag(result.country)} {country} • {category} • {result.node.node_id[:4].upper()}"


def build_payloads(
    results: list[CheckResult],
    *,
    config: BuildConfig,
    countries: dict[str, str],
    history: dict[str, Any],
    source_stats: list[dict[str, Any]],
    generated_at: datetime,
    check_mode: str,
) -> dict[Path, bytes]:
    links = [item.node.link_with_name(display_name(item, countries)) for item in results]
    raw_subscription = "\n".join(links) + "\n"
    encoded_subscription = base64.b64encode(raw_subscription.encode()).decode("ascii") + "\n"
    utc_label = generated_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    stats = {
        "schema_version": 2,
        "status": "diagnostic"
        if check_mode != "xray"
        else ("healthy" if len(results) >= config.target_count else "degraded"),
        "check_mode": check_mode,
        "updated_at": utc_label,
        "updated_msk": generated_at.astimezone(MOSCOW).isoformat(timespec="seconds"),
        "update_interval_minutes": 10,
        "total": len(results),
        "subscription_file": config.paths.subscription_base64.name,
        "sources": source_stats,
        "servers": [
            {
                "id": item.node.node_id,
                "name": display_name(item, countries),
                "country": item.country,
                "country_name": countries.get(item.country, "Локация не определена"),
                "country_flag": country_flag(item.country),
                "category": item.node.category,
                "category_name": _CATEGORY_NAMES.get(item.node.category, item.node.category),
                "protocol": item.node.scheme.upper(),
                "transport": item.node.transport,
                "security": item.node.security,
                "host": item.node.host,
                "ip": item.node.host,
                "port": item.node.port,
                "ping": item.tcp_ms,
                "tcp_ms": item.tcp_ms,
                "http_ms": item.http_ms,
                "speed_mbps": item.speed_mbps,
                "score": item.score,
                "source": item.node.source_name,
                "checked_at": item.checked_at,
            }
            for item in results
        ],
    }
    return {
        config.paths.subscription_raw: raw_subscription.encode(),
        config.paths.subscription_base64: encoded_subscription.encode("ascii"),
        config.paths.stats: (json.dumps(stats, ensure_ascii=False, indent=2) + "\n").encode(),
        config.paths.history: (
            json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }


def atomic_publish(payloads: dict[Path, bytes]) -> None:
    temporary: list[tuple[Path, Path]] = []
    try:
        for target, content in payloads.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temp_path = Path(temp_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fchmod(handle.fileno(), 0o644)
                    os.fsync(handle.fileno())
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
            temporary.append((temp_path, target))
        for temp_path, target in temporary:
            os.replace(temp_path, target)
    finally:
        for temp_path, _ in temporary:
            temp_path.unlink(missing_ok=True)

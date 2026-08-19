from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from .config import (
    ConfigError,
    load_raw_config,
    parse_sources,
    save_raw_config,
    suggest_source_id,
)
from .models import Source

_CATEGORY_ALIASES = {
    "universal": "universal",
    "internet": "universal",
    "обычный": "universal",
    "whitelist": "whitelist",
    "white": "whitelist",
    "белые": "whitelist",
    "белый": "whitelist",
}


def normalize_category(value: str) -> str:
    key = value.strip().lower()
    if key not in _CATEGORY_ALIASES:
        raise ConfigError("категория должна быть universal или whitelist")
    return _CATEGORY_ALIASES[key]


def source_to_row(source: Source) -> dict[str, object]:
    return {
        "id": source.source_id,
        "name": source.name,
        "url": source.url,
        "category": source.category,
        "enabled": source.enabled,
    }


def _write_sources(path: Path, raw: dict, sources: Sequence[Source]) -> list[Source]:
    raw["sources"] = [source_to_row(source) for source in sources]
    parsed = parse_sources(raw["sources"])
    save_raw_config(path, raw)
    return parsed


def list_sources(path: str | Path) -> list[Source]:
    _, raw = load_raw_config(path)
    return parse_sources(raw.get("sources"))


def add_source(
    path: str | Path,
    url: str,
    *,
    name: str | None = None,
    source_id: str | None = None,
    category: str = "universal",
    enabled: bool = True,
) -> Source:
    config_path, raw = load_raw_config(path)
    sources = parse_sources(raw.get("sources"))
    clean_url = url.strip()
    normalized = clean_url.rstrip("/")
    if any(item.url.rstrip("/") == normalized for item in sources):
        raise ConfigError(f"такой URL уже есть среди источников: {clean_url}")
    existing_ids = {item.source_id for item in sources}
    new_id = (source_id or "").strip().lower() or suggest_source_id(clean_url, existing_ids)
    host = urlsplit(clean_url).hostname or new_id
    new_source = Source(
        new_id,
        (name or "").strip() or host,
        clean_url,
        normalize_category(category),
        enabled,
    )
    updated = _write_sources(config_path, raw, [*sources, new_source])
    return next(item for item in updated if item.source_id == new_source.source_id)


def _match_source(sources: Sequence[Source], identifier: str) -> Source:
    needle = identifier.strip()
    if not needle:
        raise ConfigError("укажите id или URL источника")
    normalized = needle.rstrip("/")
    lowered = needle.lower()
    matches = [
        item
        for item in sources
        if item.source_id == lowered
        or item.url.rstrip("/") == normalized
        or item.name.casefold() == needle.casefold()
        or (urlsplit(item.url).hostname or "").lower() == lowered
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ConfigError(f"источник не найден: {needle}")
    raise ConfigError(f"название «{needle}» подходит нескольким источникам — укажите id")


def remove_source(path: str | Path, identifier: str) -> Source:
    config_path, raw = load_raw_config(path)
    sources = parse_sources(raw.get("sources"))
    target = _match_source(sources, identifier)
    remaining = [item for item in sources if item.source_id != target.source_id]
    if not remaining:
        raise ConfigError("нельзя удалить последний источник")
    if target.enabled and not any(item.enabled for item in remaining):
        raise ConfigError("нельзя удалить последний включённый источник — сначала включите другой")
    _write_sources(config_path, raw, remaining)
    return target


def set_source_enabled(path: str | Path, identifier: str, enabled: bool) -> Source:
    config_path, raw = load_raw_config(path)
    sources = parse_sources(raw.get("sources"))
    target = _match_source(sources, identifier)
    updated = [
        Source(item.source_id, item.name, item.url, item.category, enabled)
        if item.source_id == target.source_id
        else item
        for item in sources
    ]
    parsed = _write_sources(config_path, raw, updated)
    return next(item for item in parsed if item.source_id == target.source_id)


def format_sources(sources: Sequence[Source]) -> str:
    if not sources:
        return "Источники не заданы."
    lines = [f"Источники подписки: {len(sources)}"]
    for source in sources:
        state = "включён" if source.enabled else "выключен"
        category = "белые списки" if source.category == "whitelist" else "обычный интернет"
        lines.append(f"\n• {source.source_id}  [{state}]  {category}")
        lines.append(f"  {source.name}")
        lines.append(f"  {source.url}")
    return "\n".join(lines) + "\n"

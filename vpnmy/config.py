from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import Source


class ConfigError(ValueError):
    """Ошибка конфигурации сборщика."""


@dataclass(frozen=True, slots=True)
class Paths:
    subscription_base64: Path
    subscription_raw: Path
    stats: Path
    history: Path
    countries: Path


@dataclass(frozen=True, slots=True)
class BuildConfig:
    sources: tuple[Source, ...]
    paths: Paths
    target_count: int
    min_publish_count: int
    max_candidates: int
    max_per_endpoint: int
    category_quotas: dict[str, int]
    preferred_countries: tuple[str, ...]
    fetch_workers: int
    probe_workers: int
    verify_workers: int
    source_timeout_seconds: float
    tcp_timeout_seconds: float
    verify_timeout_seconds: float
    speed_test_bytes: int
    xray_bin: str
    # Верхние границы по странам позволяют держать российские узлы резервом,
    # не отдавая им большую часть подписки.
    country_limits: dict[str, int] = field(default_factory=dict)


_REQUIRED_CATEGORIES = {"universal", "whitelist"}


def _is_country_code(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 2 and value.isascii() and value.isalpha()


def _integer(data: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{key} должен быть целым числом от {minimum} до {maximum}")
    return value


def _number(data: dict[str, Any], key: str, minimum: float, maximum: float) -> float:
    value = data.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not minimum <= value <= maximum
    ):
        raise ConfigError(f"{key} должен быть числом от {minimum} до {maximum}")
    return float(value)


def _path(root: Path, value: Any, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"paths.{key} должен быть непустой строкой")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ConfigError(f"paths.{key} не должен выходить за пределы репозитория") from exc
    return candidate


def load_config(path: str | Path) -> BuildConfig:
    config_path = Path(path).resolve()
    root = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"файл конфигурации не найден: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"некорректный JSON в {config_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ConfigError("поддерживается только schema_version=1")
    source_rows = raw.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        raise ConfigError("sources должен быть непустым списком")
    source_ids: set[str] = set()
    sources: list[Source] = []
    for index, row in enumerate(source_rows):
        if not isinstance(row, dict):
            raise ConfigError(f"sources[{index}] должен быть объектом")
        try:
            source_id_raw = row["id"]
            name_raw = row["name"]
            url_raw = row["url"]
            category_raw = row["category"]
        except KeyError as exc:
            raise ConfigError(f"в sources[{index}] отсутствует поле {exc.args[0]}") from exc
        if not all(
            isinstance(value, str) for value in (source_id_raw, name_raw, url_raw, category_raw)
        ):
            raise ConfigError(f"строковые поля sources[{index}] должны быть строками")
        source_id = source_id_raw.strip()
        name = name_raw.strip()
        url = url_raw.strip()
        category = category_raw.strip().lower()
        if not source_id or not name or source_id in source_ids:
            raise ConfigError(f"некорректный или повторяющийся id источника: {source_id!r}")
        try:
            parsed_url = urlsplit(url)
            hostname = parsed_url.hostname
            _ = parsed_url.port  # проверяет диапазон и формат явно указанного порта
        except ValueError as exc:
            raise ConfigError(f"источник {source_id} содержит некорректный URL") from exc
        if parsed_url.scheme != "https" or not hostname:
            raise ConfigError(f"источник {source_id} должен использовать публичный HTTPS URL")
        if parsed_url.username or parsed_url.password:
            raise ConfigError(f"источник {source_id} не должен содержать логин или токен в URL")
        try:
            source_address = ipaddress.ip_address(hostname)
        except ValueError:
            source_address = None
        if source_address is not None and not source_address.is_global:
            raise ConfigError(f"источник {source_id} не должен указывать на локальный IP-адрес")
        if category not in _REQUIRED_CATEGORIES:
            raise ConfigError(f"неизвестная категория источника {source_id}: {category}")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"enabled источника {source_id} должен быть true или false")
        source_ids.add(source_id)
        sources.append(Source(source_id, name, url, category, enabled))
    if not any(source.enabled for source in sources):
        raise ConfigError("должен быть включён хотя бы один источник")
    paths_data = raw.get("paths")
    if not isinstance(paths_data, dict):
        raise ConfigError("paths должен быть объектом")
    paths = Paths(
        _path(root, paths_data.get("subscription_base64"), "subscription_base64"),
        _path(root, paths_data.get("subscription_raw"), "subscription_raw"),
        _path(root, paths_data.get("stats"), "stats"),
        _path(root, paths_data.get("history"), "history"),
        _path(root, paths_data.get("countries"), "countries"),
    )
    if (
        len(
            {
                paths.subscription_base64,
                paths.subscription_raw,
                paths.stats,
                paths.history,
                paths.countries,
            }
        )
        != 5
    ):
        raise ConfigError("пути входных и выходных файлов не должны совпадать")
    target = _integer(raw, "target_count", 1, 100)
    minimum = _integer(raw, "min_publish_count", 1, target)
    max_candidates = _integer(raw, "max_candidates", target, 5000)
    quotas = raw.get("category_quotas")
    if not isinstance(quotas, dict) or any(
        category not in _REQUIRED_CATEGORIES
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for category, value in quotas.items()
    ):
        raise ConfigError("category_quotas содержит некорректные значения")
    if sum(quotas.values()) > target:
        raise ConfigError("сумма category_quotas не может превышать target_count")
    country_limits_raw = raw.get("country_limits", {})
    if not isinstance(country_limits_raw, dict) or any(
        not _is_country_code(code)
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > target
        for code, value in country_limits_raw.items()
    ):
        raise ConfigError("country_limits содержит некорректные значения")
    country_limits = {code.upper(): int(value) for code, value in country_limits_raw.items()}
    preferred = raw.get("preferred_countries")
    if not isinstance(preferred, list) or any(not _is_country_code(code) for code in preferred):
        raise ConfigError("preferred_countries должен быть списком двухбуквенных ISO-кодов")
    normalized_preferred = [code.upper() for code in preferred]
    if len(normalized_preferred) != len(set(normalized_preferred)):
        raise ConfigError("preferred_countries не должен содержать повторяющиеся ISO-коды")
    xray_bin = os.environ.get("VPNMY_XRAY_BIN", raw.get("xray_bin", "xray"))
    if not isinstance(xray_bin, str) or not xray_bin.strip():
        raise ConfigError("xray_bin должен быть непустой строкой")
    return BuildConfig(
        tuple(sources),
        paths,
        target,
        minimum,
        max_candidates,
        _integer(raw, "max_per_endpoint", 1, 10),
        {key: int(value) for key, value in quotas.items()},
        tuple(normalized_preferred),
        _integer(raw, "fetch_workers", 1, 32),
        _integer(raw, "probe_workers", 1, 256),
        _integer(raw, "verify_workers", 1, 32),
        _number(raw, "source_timeout_seconds", 1, 120),
        _number(raw, "tcp_timeout_seconds", 0.1, 30),
        _number(raw, "verify_timeout_seconds", 1, 60),
        _integer(raw, "speed_test_bytes", 0, 5_000_000),
        xray_bin,
        country_limits,
    )

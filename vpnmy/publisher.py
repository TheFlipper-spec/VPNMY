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
_CATEGORY_SHORT = {"universal": "Интернет", "whitelist": "Белые списки"}
DEFAULT_PROFILE_TITLE = "FL1P VPN"
DEFAULT_PROFILE_URL = "https://theflipper-spec.github.io/VPNMY/"


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


def display_name(
    result: CheckResult, countries: dict[str, str], *, profile_title: str = DEFAULT_PROFILE_TITLE
) -> str:
    country = countries.get(result.country, "Локация не определена")
    category = _CATEGORY_SHORT.get(result.node.category, "Интернет")
    title = " ".join(profile_title.split()) or DEFAULT_PROFILE_TITLE
    return f"{country_flag(result.country)} {title} · {country} · {category} · {result.http_ms} мс"


def subscription_metadata(
    *,
    title: str = DEFAULT_PROFILE_TITLE,
    update_interval_minutes: int = 10,
    web_page_url: str = DEFAULT_PROFILE_URL,
) -> list[str]:
    clean_title = " ".join(title.replace("#", " ").split()) or DEFAULT_PROFILE_TITLE
    clean_url = web_page_url.strip() or DEFAULT_PROFILE_URL
    return [
        f"#profile-title: {clean_title}",
        f"#profile-update-interval: {max(1, int(update_interval_minutes))}",
        f"#profile-web-page-url: {clean_url}",
    ]


def build_payloads(
    results: list[CheckResult],
    *,
    config: BuildConfig,
    countries: dict[str, str],
    history: dict[str, Any],
    source_stats: list[dict[str, Any]],
    generated_at: datetime,
    check_mode: str,
    source_health: dict[str, Any] | None = None,
    ru_stats: Any = None,
    ru_results: dict[str, Any] | None = None,
) -> dict[Path, bytes]:
    title = config.profile_title or DEFAULT_PROFILE_TITLE
    web_page_url = config.profile_web_page_url or DEFAULT_PROFILE_URL
    names = [display_name(item, countries, profile_title=title) for item in results]
    links = [item.node.link_with_name(name) for item, name in zip(results, names, strict=True)]
    header = subscription_metadata(title=title, web_page_url=web_page_url)
    raw_subscription = "\n".join([*header, *links]) + "\n"
    encoded_subscription = base64.b64encode(raw_subscription.encode()).decode("ascii") + "\n"
    utc_label = generated_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    protocol_counts: dict[str, int] = {}
    for item in results:
        label = "HYSTERIA2" if item.node.is_hysteria else item.node.scheme.upper()
        protocol_counts[label] = protocol_counts.get(label, 0) + 1
    # Диагностика разнообразия и ASN — берётся из временного ключа history["_diagnostics"] если есть
    diagnostics = history.get("_diagnostics", {}) if isinstance(history.get("_diagnostics"), dict) else {}
    ru_results = ru_results or {}
    stats = {
        "schema_version": 4,
        "status": "diagnostic"
        if check_mode != "xray"
        else ("healthy" if len(results) >= config.target_count else "degraded"),
        "check_mode": check_mode,
        "updated_at": utc_label,
        "updated_msk": generated_at.astimezone(MOSCOW).isoformat(timespec="seconds"),
        "update_interval_minutes": 10,
        "profile_title": title,
        "subscription_url_fragment": title,
        "total": len(results),
        "protocols": protocol_counts,
        "quarantined_sources": sum(
            1 for row in source_stats if row.get("quarantined") and row.get("enabled")
        ),
        "subscription_file": config.paths.subscription_base64.name,
        "subscription_raw_file": config.paths.subscription_raw.name,
        "subscription_metadata_lines": len(header),
        "verification": {
            "method": "tunnel_https_xray_hysteria" if check_mode == "xray" else "tcp_udp_only",
            "cores": ["Xray", "Hysteria"] if check_mode == "xray" else [],
            "required_https_requests": 2 if check_mode == "xray" else 0,
            "measurements_per_node": config.verify_measurements if check_mode == "xray" else 0,
            "median_threshold_ms": config.verify_median_threshold_ms,
            "description": (
                "Задержка — медиана N независимых TRACE-запросов через SOCKS-туннель ядра "
                "(свежий Session на попытку, без переиспользования соединения между попытками; "
                "внутри попытки trace и подтверждение могут переиспользовать соединение, "
                "но измеряется только trace). Подтверждение — второй независимый HTTPS-запрос "
                "(generate_204/success.txt). Неудачи кодируются как timeout и входят в медиану; "
                "считаются max и jitter (разброс)."
            ),
        },
        "diversity": {
            "limits": {
                "max_per_country": config.max_per_country,
                "max_per_asn": config.max_per_asn,
                "max_per_ip": config.max_per_ip,
                "max_per_subnet": config.max_per_subnet,
                "max_per_endpoint": config.max_per_endpoint,
                "ipv4_subnet": "/24",
                "ipv6_subnet": "/48",
                "notes": (
                    "Страна используется только для разнообразия, не для оценки качества. "
                    "Для доменных endpoint используется разрешённый IP (DNS), корректно "
                    "обрабатываются IPv4 и IPv6. Выходной IP (egress) дедуплицируется отдельно от IP сервера. "
                    "ASN определяется по IP сервера через bgpview.io (только IP, без секретов), "
                    "таймаут 3с, кэш, параллельность 5; ошибка ASN не ломает сборку, неизвестный ASN "
                    "не объединяется в один провайдер — лимит ASN его пропускает, остальные лимиты остаются."
                ),
            },
            "before_selection": diagnostics.get("diversity_before", {}),
            "after_selection": diagnostics.get("diversity_after", {}),
            "excluded_by_limits": diagnostics.get("excluded_count", 0),
        },
        "asn": diagnostics.get("asn", {"status": "unknown"}),
        "ru_check": (ru_stats.as_stats_dict() if ru_stats is not None else {"enabled": False}),
        "quality": {
            "scoring": (
                "Без географического бонуса: качество = реальные проверки, надёжность в скользящем окне "
                f"(последние {config.history_recent_window} циклов), задержка (медиана, худший, разброс), "
                "стабильность (streak), скорость, защита, протокол. Старая preferred_countries читается, но не влияет."
            ),
            "preferred_countries_ignored": list(config.preferred_countries),
        },
        "sources": source_stats,
        "servers": [
            {
                "id": item.node.node_id,
                "name": display_name(item, countries, profile_title=title),
                "country": item.country,
                "country_name": countries.get(item.country, "Локация не определена"),
                "country_flag": country_flag(item.country),
                "category": item.node.category,
                "category_name": _CATEGORY_NAMES.get(item.node.category, item.node.category),
                "protocol": item.node.scheme.upper(),
                "transport": item.node.transport,
                "security": item.node.security,
                "host": item.node.host,
                "ip": item.resolved_ip or None,
                "egress_ip": getattr(item, "egress_ip", "") or None,
                "asn": getattr(item, "asn", "") or None,
                "port": item.node.port,
                "ping": item.tcp_ms,
                "tcp_ms": item.tcp_ms,
                "http_ms": item.http_ms,
                "http_max_ms": getattr(item, "http_max_ms", item.http_ms),
                "jitter_ms": getattr(item, "jitter_ms", 0),
                "attempts": getattr(item, "attempts", 1),
                "speed_mbps": item.speed_mbps,
                "score": item.score,
                "ru_ms": (
                    ru_results[item.node.node_id].latency_ms
                    if item.node.node_id in ru_results
                    and getattr(ru_results[item.node.node_id], "ok", None) is True
                    else None
                ),
                "verified": check_mode == "xray" and item.checks_passed >= 2,
                "checks_passed": item.checks_passed,
                "success_streak": int(
                    history.get("nodes", {}).get(item.node.node_id, {}).get("streak", 0)
                ),
                "source": item.node.source_name,
                "checked_at": item.checked_at,
            }
            for item in results
        ],
    }
    payloads: dict[Path, bytes] = {
        config.paths.subscription_raw: raw_subscription.encode(),
        config.paths.subscription_base64: encoded_subscription.encode("ascii"),
        config.paths.stats: (json.dumps(stats, ensure_ascii=False, indent=2) + "\n").encode(),
        config.paths.history: (
            json.dumps({k: v for k, v in history.items() if k != "_diagnostics"}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }
    if config.paths.source_health is not None and source_health is not None:
        payloads[config.paths.source_health] = (
            json.dumps(source_health, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
    return payloads


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

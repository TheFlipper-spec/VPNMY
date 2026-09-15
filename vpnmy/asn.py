"""Определение ASN по IP сервера.

Использует публичный источник bgpview.io (https://api.bgpview.io) без API-ключа,
документированный как бесплатный для некоммерческого использования. Отправляет
только IP-адрес, не содержит ссылок на конфигурации, пароли, UUID и токены.
При недоступности сервиса или ошибке — возвращает пустую строку и не ломает сборку.
Не объединяет неизвестные ASN в один «общий провайдер»: неизвестные пропускаются
при проверке лимита max_per_asn, остальные лимиты (страна/IP/подсеть) остаются доступны.

Характеристики:
- Таймаут 3 секунды, ограничение параллельности 5 запросов, кэш в памяти.
- Поддерживает IPv4 и IPv6 (передаёт адрес как есть).
- Не требует локальной базы GeoIP.

Альтернативные источники с похожими условиями: ipwho.is, ip-api.com — при необходимости
можно заменить URL и парсер ответа.
"""

from __future__ import annotations

import ipaddress
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

LOGGER = logging.getLogger(__name__)

# Публичный API: https://api.bgpview.io/ip/{ip}
BGPVIEW_URL = "https://api.bgpview.io/ip/{ip}"
# Альтернатива: https://ipwho.is/{ip} -> {"connection":{"asn":15169},...}
TIMEOUT = 3.0
MAX_WORKERS = 5


def _fetch_asn(ip: str, session: requests.Session) -> str:
    # Проверка что это глобальный IP; приватные/локальные пропускаем (ASN неизвестен).
    try:
        addr = ipaddress.ip_address(ip)
        if not addr.is_global:
            return ""
    except ValueError:
        return ""
    try:
        resp = session.get(BGPVIEW_URL.format(ip=ip), timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # Ожидаемый формат: {"status":"ok","data":{"asn":15169, ...}}
        # или {"data":{"asn":...}} — защищаемся от вариаций.
        if isinstance(data, dict):
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            asn = payload.get("asn") if isinstance(payload, dict) else None
            if asn is not None:
                # Нормализуем к виду "AS15169"
                asn_str = str(asn).strip().upper()
                if asn_str and not asn_str.startswith("AS"):
                    asn_str = "AS" + asn_str.lstrip("AS")
                # Проверка на валидный номер
                if asn_str[2:].isdigit():
                    return asn_str
        return ""
    except Exception as exc:  # noqa: BLE001 — любой сбой не должен ломать сборку
        LOGGER.debug("ASN lookup failed for %s: %s", ip, exc)
        return ""


def enrich_asns(
    ip_to_asn: dict[str, str],
    *,
    timeout: float = TIMEOUT,
    workers: int = MAX_WORKERS,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Обогащает словарь ip->asn, заполняя только пустые/отсутствующие ASN.

    Возвращает новый словарь ip->asn (копия). Не отправляет ничего кроме IP.
    При ошибках оставляет значение пустой строкой и продолжает.
    """
    # Собираем только те IP, для которых ASN неизвестен и это глобальный адрес.
    pending = [ip for ip, asn in ip_to_asn.items() if not asn]
    if not pending:
        return dict(ip_to_asn)
    # Кэш в пределах вызова уже в ip_to_asn.
    close_session = False
    if session is None:
        session = requests.Session()
        session.trust_env = False
        session.headers["User-Agent"] = "FL1P-VPN-ASN/1.0"
        close_session = True
    try:
        # Ограничиваем параллельность
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as executor:
            futures = {executor.submit(_fetch_asn, ip, session): ip for ip in pending}
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    asn = future.result()
                except Exception:
                    asn = ""
                ip_to_asn[ip] = asn
    finally:
        if close_session:
            session.close()
    return dict(ip_to_asn)


def get_asn(ip: str, *, session: requests.Session | None = None) -> str:
    """Синхронное получение ASN для одного IP (удобно для тестов с mock)."""
    if session is None:
        session = requests.Session()
        session.trust_env = False
        close = True
    else:
        close = False
    try:
        return _fetch_asn(ip, session)
    finally:
        if close:
            session.close()

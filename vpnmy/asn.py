"""Определение ASN по IP сервера.

Основной источник — ipwho.is (HTTPS, без API-ключа), резервный — api.bgpview.io.
Отправляется только IP-адрес, без конфигураций, паролей, UUID и токенов.
При недоступности обоих сервисов возвращается пустая строка, сборка не ломается.
Неизвестные ASN не объединяются в один «общий провайдер»: лимит max_per_asn
их пропускает, остальные лимиты (страна/IP/подсеть) продолжают работать.

Характеристики:
- Таймаут 3 секунды, параллельность 5 запросов.
- Поддерживает IPv4 и IPv6 (передаёт адрес как есть).
- Понимает оба формата ответа: ipwho.is (connection.asn) и bgpview (data.asn).
- Не требует локальной базы GeoIP.
"""

from __future__ import annotations

import ipaddress
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

LOGGER = logging.getLogger(__name__)

# Основной и резервный публичные API. Оба принимают только IP.
IPWHOIS_URL = "https://ipwho.is/{ip}"
BGPVIEW_URL = "https://api.bgpview.io/ip/{ip}"
TIMEOUT = 3.0
MAX_WORKERS = 5


def _parse_asn(data: object) -> str:
    """Извлекает номер ASN из ответа ipwho.is или bgpview.io."""
    if not isinstance(data, dict):
        return ""
    candidates: list[object] = [data.get("asn")]
    connection = data.get("connection")
    if isinstance(connection, dict):
        candidates.append(connection.get("asn"))
    payload = data.get("data")
    if isinstance(payload, dict):
        candidates.append(payload.get("asn"))
    for value in candidates:
        if value is None or isinstance(value, bool):
            continue
        asn_str = str(value).strip().upper()
        if not asn_str:
            continue
        if not asn_str.startswith("AS"):
            asn_str = "AS" + asn_str
        if asn_str[2:].isdigit():
            return asn_str
    return ""


def _fetch_asn(ip: str, session: requests.Session) -> str:
    # Проверка что это глобальный IP; приватные/локальные пропускаем (ASN неизвестен).
    try:
        addr = ipaddress.ip_address(ip)
        if not addr.is_global:
            return ""
    except ValueError:
        return ""
    for url in (IPWHOIS_URL, BGPVIEW_URL):
        try:
            resp = session.get(url.format(ip=ip), timeout=TIMEOUT)
            resp.raise_for_status()
            asn = _parse_asn(resp.json())
            if asn:
                return asn
        except Exception as exc:  # noqa: BLE001 — сбой не должен ломать сборку
            LOGGER.debug("ASN lookup failed for %s (%s): %s", ip, url, exc)
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

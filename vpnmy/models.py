from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

_NON_CONFIG_METADATA_KEYS = {
    "description",
    "descriptions",
    "email",
    "name",
    "ps",
    "remark",
    "remarks",
    "telegram",
}


def encode_remark(name: str) -> str:
    """Человекочитаемое имя узла для фрагмента URI и поля ps."""
    cleaned = " ".join(str(name).replace("#", " ").split())
    return "".join(
        char if char.isprintable() and char != "#" else quote(char, safe="") for char in cleaned
    )


@dataclass(frozen=True, slots=True)
class Source:
    """Доверенный публичный источник конфигураций."""

    source_id: str
    name: str
    url: str
    category: str
    enabled: bool = True


@dataclass(slots=True)
class Node:
    """Нормализованная конфигурация прокси без результатов проверки."""

    scheme: str
    host: str
    port: int
    original_link: str
    source_id: str
    source_name: str
    category: str
    user: str
    options: dict[str, str] = field(default_factory=dict)
    original_name: str = ""
    vmess: dict[str, Any] | None = None

    @property
    def canonical_link(self) -> str:
        """Конфигурация без названия и порядка query-полей для дедупликации."""
        if self.scheme == "vmess" and self.vmess is not None:
            payload = {
                key: value
                for key, value in self.vmess.items()
                if key.casefold() not in _NON_CONFIG_METADATA_KEYS
            }
        else:
            payload = {
                "scheme": self.scheme,
                "host": self.host.lower(),
                "port": self.port,
                "user": self.user,
                "options": {
                    key: value
                    for key, value in self.options.items()
                    if key.casefold() not in _NON_CONFIG_METADATA_KEYS
                },
            }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def node_id(self) -> str:
        return hashlib.sha256(self.canonical_link.encode("utf-8")).hexdigest()[:16]

    @property
    def endpoint_key(self) -> str:
        return f"{self.host.lower()}:{self.port}"

    @property
    def is_hysteria(self) -> bool:
        return self.scheme in {"hysteria2", "hy2"}

    @property
    def transport(self) -> str:
        if self.is_hysteria:
            return "hysteria2"
        value = self.options.get("type", "tcp").lower()
        return value if value else "tcp"

    @property
    def security(self) -> str:
        if self.is_hysteria:
            return "tls"
        default = "tls" if self.scheme == "trojan" else "none"
        value = self.options.get("security", default).lower()
        if value in {"", "false", "0"}:
            return "none"
        return value

    @property
    def probe_port(self) -> int:
        """Порт для сетевой предпроверки (у port-hopping это первый порт диапазона)."""
        hopping = self.options.get("mport", "")
        if self.is_hysteria and hopping:
            match = re.search(r"\d+", hopping)
            if match:
                port = int(match.group())
                if 1 <= port <= 65535:
                    return port
        return self.port

    def link_with_name(self, name: str) -> str:
        remark = encode_remark(name)
        if self.scheme == "vmess" and self.vmess is not None:
            payload = dict(self.vmess)
            payload["ps"] = remark
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return "vmess://" + base64.b64encode(raw).decode("ascii") + "#" + remark
        parts = urlsplit(self.original_link)
        return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, remark))


@dataclass(frozen=True, slots=True)
class ProbeResult:
    node: Node
    tcp_ms: int
    resolved_ip: str = ""

    @property
    def endpoint_key(self) -> str:
        """Физический адрес узла, если DNS уже был разрешён."""
        return f"{self.resolved_ip or self.node.host.lower()}:{self.node.port}"


@dataclass(frozen=True, slots=True)
class CheckResult:
    node: Node
    tcp_ms: int
    http_ms: int  # медиана задержки (мс) из серии измерений через туннель
    speed_mbps: float
    country: str
    checked_at: str
    score: float = 0.0
    resolved_ip: str = ""
    checks_passed: int = 1
    # --- Новые поля для измерения качества и разнообразия (совместимы со старыми данными) ---
    # Выходной IP, полученный через туннель (Cloudflare trace ip). Может совпадать у разных входов.
    egress_ip: str = ""
    # ASN сервера (определяется по resolved_ip). Пустая строка = неизвестен.
    asn: str = ""
    # Наихудшая задержка среди попыток (мс). Если измерение одно — равна http_ms.
    http_max_ms: int = 0
    # Разброс (max - min) среди попыток, показывает нестабильность.
    jitter_ms: int = 0
    # Сколько попыток измерения выполнено и сколько из них успешно прошли двойную проверку.
    attempts: int = 1
    # Исходные выборки задержки (мс); неудачные попытки кодируются как таймаут.
    samples: tuple[int, ...] = ()
    # Скорость измерена только на одной из попыток, чтобы не утраивать трафик.
    # По умолчанию уже задаётся speed_mbps — совместимость сохраняется.

    @property
    def endpoint_key(self) -> str:
        """Физический адрес узла, используемый для защиты от дублей."""
        return f"{self.resolved_ip or self.node.host.lower()}:{self.node.port}"

    @property
    def server_ip(self) -> str:
        """Нормализованный IP сервера (resolved_ip или хост, если IP неизвестен)."""
        return self.resolved_ip or ""

    @property
    def median_ms(self) -> int:
        return self.http_ms

    @property
    def max_ms(self) -> int:
        return self.http_max_ms or self.http_ms

    @property
    def jitter(self) -> int:
        return self.jitter_ms

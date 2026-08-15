from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


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
            payload = {key: value for key, value in self.vmess.items() if key != "ps"}
        else:
            payload = {
                "scheme": self.scheme,
                "host": self.host.lower(),
                "port": self.port,
                "user": self.user,
                "options": self.options,
            }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def node_id(self) -> str:
        return hashlib.sha256(self.canonical_link.encode("utf-8")).hexdigest()[:16]

    @property
    def endpoint_key(self) -> str:
        return f"{self.host.lower()}:{self.port}"

    @property
    def transport(self) -> str:
        value = self.options.get("type", "tcp").lower()
        return value if value else "tcp"

    @property
    def security(self) -> str:
        default = "tls" if self.scheme == "trojan" else "none"
        value = self.options.get("security", default).lower()
        if value in {"", "false", "0"}:
            return "none"
        return value

    def link_with_name(self, name: str) -> str:
        if self.scheme == "vmess" and self.vmess is not None:
            payload = dict(self.vmess)
            payload["ps"] = name
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return "vmess://" + base64.b64encode(raw).decode("ascii")
        parts = urlsplit(self.original_link)
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc, parts.path, parts.query, quote(name, safe=""))
        )


@dataclass(frozen=True, slots=True)
class ProbeResult:
    node: Node
    tcp_ms: int


@dataclass(frozen=True, slots=True)
class CheckResult:
    node: Node
    tcp_ms: int
    http_ms: int
    speed_mbps: float
    country: str
    checked_at: str
    score: float = 0.0

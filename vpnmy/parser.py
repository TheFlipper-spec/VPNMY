from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
import uuid
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from .models import Node, Source

SUPPORTED_SCHEMES = ("vless", "vmess", "trojan")
SUPPORTED_TRANSPORTS = {
    "tcp",
    "raw",
    "ws",
    "grpc",
    "http",
    "h2",
    "httpupgrade",
    "xhttp",
    "splithttp",
    "kcp",
    "quic",
}
_LINK_RE = re.compile(r"(?i)(?:vless|vmess|trojan)://[^\s<>\"']+")
_BASE64_RE = re.compile(r"^[A-Za-z0-9_+/=\s-]+$")


class ParseError(ValueError):
    """Конфигурация синтаксически некорректна или небезопасна."""


def _decode_base64(value: str) -> str | None:
    compact = "".join(value.split())
    if len(compact) < 16 or not _BASE64_RE.fullmatch(compact):
        return None
    padded = compact + "=" * (-len(compact) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(padded).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            continue
        if any(f"{scheme}://" in decoded.lower() for scheme in SUPPORTED_SCHEMES):
            return decoded
    return None


def extract_links(text: str, *, max_text_bytes: int = 8_000_000) -> list[str]:
    if len(text.encode("utf-8", errors="ignore")) > max_text_bytes:
        raise ParseError("ответ источника превышает допустимый размер")
    documents = [text]
    decoded = _decode_base64(text)
    if decoded is not None:
        documents.append(decoded)
    found: dict[str, None] = {}
    for document in documents:
        for raw_line in document.replace("\x00", "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith(tuple(f"{scheme}://" for scheme in SUPPORTED_SCHEMES)):
                found.setdefault(line, None)
                continue
            for match in _LINK_RE.findall(line):
                found.setdefault(match, None)
            nested = _decode_base64(line)
            if nested is not None:
                for match in _LINK_RE.findall(nested):
                    found.setdefault(match, None)
    return list(found)


def _validate_host(host: str) -> str:
    host = host.strip().strip("[]").rstrip(".")
    if not host or len(host) > 253 or any(char.isspace() for char in host):
        raise ParseError("некорректный адрес сервера")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ParseError("некорректное доменное имя") from exc
        labels = ascii_host.split(".")
        if any(not label or len(label) > 63 for label in labels):
            raise ParseError("некорректное доменное имя") from None
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
            raise ParseError("некорректное доменное имя") from None
        return ascii_host
    if not address.is_global:
        raise ParseError("локальные и служебные IP-адреса запрещены")
    return address.compressed


def _validate_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ParseError("некорректный порт") from exc
    if not 1 <= port <= 65535:
        raise ParseError("порт находится вне диапазона 1..65535")
    return port


def _validate_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ParseError("некорректный UUID") from exc


def _options(query: str) -> dict[str, str]:
    if len(query) > 32_000:
        raise ParseError("слишком длинная строка параметров")
    result: dict[str, str] = {}
    for key, value in parse_qsl(query, keep_blank_values=True, max_num_fields=128):
        result.setdefault(key, value)
    return result


def _validate_common(node: Node) -> Node:
    if node.transport not in SUPPORTED_TRANSPORTS:
        raise ParseError(f"неподдерживаемый транспорт: {node.transport}")
    if node.security not in {"none", "tls", "reality"}:
        raise ParseError(f"неподдерживаемая защита: {node.security}")
    if node.security == "reality" and (not node.options.get("pbk") or not node.options.get("sni")):
        raise ParseError("Reality-конфигурация не содержит pbk или sni")
    return node


def _parse_vmess(link: str, source: Source) -> Node:
    payload = link[len("vmess://") :].split("#", 1)[0].strip()
    padded = payload + "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded).decode("utf-8")
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ParseError("некорректный VMess payload") from exc
    if not isinstance(data, dict):
        raise ParseError("VMess payload должен быть объектом")
    host = _validate_host(str(data.get("add", "")))
    port = _validate_port(data.get("port"))
    user = _validate_uuid(str(data.get("id", "")))
    transport = str(data.get("net") or "tcp").lower()
    tls_value = str(data.get("tls") or "").lower()
    security = "tls" if tls_value in {"tls", "1", "true"} else "none"
    options = {
        "type": transport,
        "security": security,
        "sni": str(data.get("sni") or data.get("serverName") or data.get("host") or ""),
        "host": str(data.get("host") or ""),
        "path": str(data.get("path") or "/"),
        "serviceName": str(data.get("serviceName") or data.get("path") or ""),
        "fp": str(data.get("fp") or "chrome"),
        "aid": str(data.get("aid") or "0"),
        "scy": str(data.get("scy") or data.get("security") or "auto"),
        "alpn": str(data.get("alpn") or ""),
    }
    node = Node(
        "vmess",
        host,
        port,
        link,
        source.source_id,
        source.name,
        source.category,
        user,
        options,
        str(data.get("ps") or ""),
        data,
    )
    return _validate_common(node)


def parse_link(link: str, source: Source) -> Node:
    link = link.replace("\x00", "").strip()
    scheme = link.split(":", 1)[0].lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ParseError("неподдерживаемый протокол")
    if scheme == "vmess":
        return _parse_vmess(link, source)
    parts = urlsplit(link)
    if not parts.hostname:
        raise ParseError("URI не содержит адрес сервера")
    host = _validate_host(parts.hostname)
    try:
        port = _validate_port(parts.port)
    except ValueError as exc:
        raise ParseError("некорректный порт") from exc
    authority = parts.netloc.rsplit("@", 1)
    if len(authority) != 2 or not authority[0]:
        raise ParseError("URI не содержит идентификатор пользователя")
    user = unquote(authority[0])
    if scheme == "vless":
        user = _validate_uuid(user)
    elif len(user) > 512:
        raise ParseError("слишком длинный Trojan-пароль")
    options = _options(parts.query)
    if scheme == "vless" and options.get("encryption", "none").lower() != "none":
        raise ParseError("VLESS поддерживает только encryption=none")
    node = Node(
        scheme,
        host,
        port,
        link,
        source.source_id,
        source.name,
        source.category,
        user,
        options,
        unquote(parts.fragment),
    )
    return _validate_common(node)


def parse_source(text: str, source: Source) -> tuple[list[Node], int]:
    nodes: dict[str, Node] = {}
    rejected = 0
    for link in extract_links(text):
        try:
            node = parse_link(link, source)
        except (ParseError, ValueError):
            rejected += 1
            continue
        nodes.setdefault(node.canonical_link, node)
    return list(nodes.values()), rejected


def deduplicate(nodes: Iterable[Node]) -> list[Node]:
    unique: dict[str, Node] = {}
    for node in nodes:
        unique.setdefault(node.canonical_link, node)
    return list(unique.values())

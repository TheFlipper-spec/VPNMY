"""Проверка согласованности опубликованных файлов подписки.

Модуль используется и тестами, и GitHub Actions. Проверки намеренно не
основаны на ``assert``: оптимизация Python не должна отключать защиту перед
публикацией, а сообщение об ошибке должно указывать на повреждённое поле.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config
from .models import Source
from .parser import SUPPORTED_SCHEMES, ParseError, parse_link

_LINK_PREFIXES = tuple(f"{scheme}://" for scheme in SUPPORTED_SCHEMES)
_VALIDATION_SOURCE = Source(
    "artifact-validation",
    "Проверка опубликованной подписки",
    "https://example.com/subscription",
    "universal",
)


class ArtifactError(ValueError):
    """Опубликованные файлы отсутствуют, повреждены или не согласованы."""


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    total: int
    metadata_lines: int
    schema_version: int
    check_mode: str


def _read_text(path: Path, encoding: str) -> str:
    try:
        return path.read_text(encoding=encoding)
    except (OSError, UnicodeError) as exc:
        raise ArtifactError(f"не удалось прочитать {path}: {exc}") from exc


def _load_stats(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, "utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"некорректный JSON в {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"{path} должен содержать JSON-объект")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ArtifactError(f"stats.json: {field} должен быть целым числом не меньше {minimum}")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ArtifactError(f"stats.json: {field} должен быть непустой строкой")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactError(f"stats.json: {field} содержит некорректное время") from exc
    if timestamp.tzinfo is None:
        raise ArtifactError(f"stats.json: {field} должен содержать часовой пояс")
    return timestamp


def _decode_subscription(path: Path) -> str:
    encoded = _read_text(path, "ascii")
    compact = "".join(encoded.split())
    if not compact:
        raise ArtifactError(f"{path} пуст")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ArtifactError(f"{path} содержит некорректный Base64: {exc}") from exc
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError(f"{path} после Base64-декодирования не является UTF-8") from exc


def _split_raw(raw: str) -> tuple[list[str], list[str]]:
    if not raw.endswith("\n"):
        raise ArtifactError("subscription.txt должен завершаться переводом строки")
    lines = raw.splitlines()
    if not lines:
        raise ArtifactError("subscription.txt пуст")
    if any(not line.strip() for line in lines):
        raise ArtifactError("subscription.txt содержит пустую строку")

    metadata: list[str] = []
    links: list[str] = []
    links_started = False
    for line_number, line in enumerate(lines, start=1):
        if line.startswith("#"):
            if links_started:
                raise ArtifactError(
                    f"subscription.txt:{line_number}: метаданные должны находиться перед узлами"
                )
            metadata.append(line)
        elif line.lower().startswith(_LINK_PREFIXES):
            links_started = True
            links.append(line)
        else:
            raise ArtifactError(
                f"subscription.txt:{line_number}: неизвестная строка вместо метаданных или VPN URI"
            )
    if not links:
        raise ArtifactError("subscription.txt не содержит VPN URI")
    if len(links) != len(set(links)):
        raise ArtifactError("subscription.txt содержит одинаковые VPN URI")
    return metadata, links


def _validate_rows(links: list[str], servers: list[Any]) -> None:
    node_ids: set[str] = set()
    for index, (link, server) in enumerate(zip(links, servers, strict=True)):
        field = f"servers[{index}]"
        if not isinstance(server, dict):
            raise ArtifactError(f"stats.json: {field} должен быть объектом")
        try:
            node = parse_link(link, _VALIDATION_SOURCE)
        except (ParseError, ValueError) as exc:
            raise ArtifactError(
                f"subscription.txt: VPN URI #{index + 1} не разобран: {exc}"
            ) from exc

        server_id = server.get("id")
        if server_id != node.node_id:
            raise ArtifactError(f"stats.json: {field}.id не соответствует VPN URI #{index + 1}")
        if server_id in node_ids:
            raise ArtifactError(f"stats.json: повторяющийся id узла {server_id}")
        node_ids.add(server_id)

        protocol = server.get("protocol")
        if not isinstance(protocol, str) or protocol.upper() != node.scheme.upper():
            raise ArtifactError(f"stats.json: {field}.protocol не соответствует VPN URI")
        name = server.get("name")
        if not isinstance(name, str) or not name or name != node.original_name:
            raise ArtifactError(f"stats.json: {field}.name не соответствует имени в VPN URI")
        _timestamp(server.get("checked_at"), f"{field}.checked_at")


def validate_artifacts(
    subscription_base64: Path,
    subscription_raw: Path,
    stats_path: Path,
    *,
    production: bool = False,
    min_count: int = 0,
) -> ArtifactSummary:
    """Проверяет Base64, raw-подписку и соответствующий им ``stats.json``."""

    raw = _read_text(subscription_raw, "utf-8")
    decoded = _decode_subscription(subscription_base64)
    if decoded != raw:
        raise ArtifactError("FL1PVPN после Base64-декодирования не совпадает с subscription.txt")

    metadata, links = _split_raw(raw)
    stats = _load_stats(stats_path)
    schema_version = _integer(stats.get("schema_version"), "schema_version", minimum=1)
    total = _integer(stats.get("total"), "total")
    servers = stats.get("servers")
    if not isinstance(servers, list):
        raise ArtifactError("stats.json: servers должен быть списком")
    if total != len(servers) or total != len(links):
        raise ArtifactError(
            "число VPN URI не совпадает со stats.total и длиной stats.servers "
            f"({len(links)} != {total} != {len(servers)})"
        )
    if total < min_count:
        raise ArtifactError(f"опубликовано {total} узлов, требуется минимум {min_count}")

    if stats.get("subscription_file") not in {None, subscription_base64.name}:
        raise ArtifactError("stats.json: subscription_file указывает не на FL1PVPN")
    if stats.get("subscription_raw_file") not in {None, subscription_raw.name}:
        raise ArtifactError("stats.json: subscription_raw_file указывает не на subscription.txt")
    _timestamp(stats.get("updated_at"), "updated_at")
    _validate_rows(links, servers)

    declared_metadata = stats.get("subscription_metadata_lines")
    if declared_metadata is not None and _integer(
        declared_metadata, "subscription_metadata_lines"
    ) != len(metadata):
        raise ArtifactError(
            "stats.json: subscription_metadata_lines не совпадает с числом строк метаданных"
        )

    check_mode = stats.get("check_mode")
    if not isinstance(check_mode, str) or not check_mode:
        raise ArtifactError("stats.json: check_mode должен быть непустой строкой")

    if production:
        if schema_version < 3:
            raise ArtifactError("production-артефакты должны использовать schema_version >= 3")
        if metadata:
            raise ArtifactError("production-подписка должна содержать только VPN URI")
        if declared_metadata is None:
            raise ArtifactError("stats.json: отсутствует subscription_metadata_lines")
        if check_mode != "xray":
            raise ArtifactError("production-подписка должна быть проверена в режиме xray")
        if stats.get("status") not in {"healthy", "degraded"}:
            raise ArtifactError("stats.json: production-статус должен быть healthy или degraded")
        verification = stats.get("verification")
        if not isinstance(verification, dict):
            raise ArtifactError("stats.json: отсутствует объект verification")
        if verification.get("method") != "xray_https":
            raise ArtifactError("stats.json: verification.method должен быть xray_https")
        required_checks = _integer(
            verification.get("required_https_requests"),
            "verification.required_https_requests",
            minimum=2,
        )
        for index, server in enumerate(servers):
            if server.get("verified") is not True:
                raise ArtifactError(f"stats.json: servers[{index}] не помечен как проверенный")
            checks_passed = _integer(server.get("checks_passed"), f"servers[{index}].checks_passed")
            if checks_passed < required_checks:
                raise ArtifactError(
                    f"stats.json: servers[{index}] прошёл только {checks_passed} HTTPS-проверок"
                )

    return ArtifactSummary(total, len(metadata), schema_version, check_mode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Проверяет опубликованные файлы VPN-подписки")
    parser.add_argument("--config", default="config/subscription.json")
    parser.add_argument(
        "--production",
        action="store_true",
        help="требовать Xray, двойную HTTPS-проверку, schema v3 и метаданные профиля",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        summary = validate_artifacts(
            config.paths.subscription_base64,
            config.paths.subscription_raw,
            config.paths.stats,
            production=args.production,
            min_count=config.min_publish_count if args.production else 0,
        )
    except (ArtifactError, ConfigError) as exc:
        print(f"Ошибка проверки артефактов: {exc}")
        return 1
    print(
        "Артефакты согласованы: "
        f"узлов={summary.total}, метаданных={summary.metadata_lines}, "
        f"schema={summary.schema_version}, режим={summary.check_mode}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

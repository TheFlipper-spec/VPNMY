from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .builder import BuildError, build_subscription
from .config import ConfigError, load_config
from .sources import (
    add_source,
    format_sources,
    list_sources,
    remove_source,
    set_source_enabled,
)
from .xray import XrayError


@contextmanager
def process_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BuildError("другой экземпляр сборщика уже работает") from exc
        yield


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Собирает и проверяет публичную VPN-подписку для пользователей из России.\n\n"
            "Источники:\n"
            "  python main.py sources\n"
            "  python main.py sources add https://example.com/sub --name «Мой список»\n"
            "  python main.py sources rm vedalink\n"
            "  python main.py sources off ru-whitelist-pool\n"
            "  python main.py sources on ru-whitelist-pool"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default="config/subscription.json", help="путь к JSON-конфигурации"
    )
    parser.add_argument("--dry-run", action="store_true", help="проверить всё, но не менять файлы")
    parser.add_argument(
        "--skip-deep-check", action="store_true", help="не запускать Xray (диагностический режим)"
    )
    parser.add_argument("--verbose", action="store_true", help="подробный вывод")
    return parser


def _sources_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py sources",
        description="Добавление, удаление и включение источников подписки.",
    )
    parser.add_argument(
        "--config", default="config/subscription.json", help="путь к JSON-конфигурации"
    )
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="показать все источники")
    add = sub.add_parser("add", help="добавить HTTPS-источник")
    add.add_argument("url", help="публичный HTTPS URL подписки")
    add.add_argument("--name", help="человекочитаемое название")
    add.add_argument("--id", dest="source_id", help="короткий id, например vlessforu")
    add.add_argument(
        "--category",
        default="universal",
        help="universal или whitelist",
    )
    add.add_argument("--disabled", action="store_true", help="добавить выключенным")
    remove = sub.add_parser("rm", aliases=["remove", "del"], help="удалить источник")
    remove.add_argument("identifier", help="id, название или URL")
    enable = sub.add_parser("on", aliases=["enable"], help="включить источник")
    enable.add_argument("identifier", help="id, название или URL")
    disable = sub.add_parser("off", aliases=["disable"], help="выключить источник")
    disable.add_argument("identifier", help="id, название или URL")
    return parser


def _run_sources(argv: Sequence[str]) -> int:
    parser = _sources_parser()
    args = parser.parse_args(list(argv))
    action = args.action or "list"
    try:
        if action == "list":
            print(format_sources(list_sources(args.config)), end="")
            return 0
        if action == "add":
            source = add_source(
                args.config,
                args.url,
                name=args.name,
                source_id=args.source_id,
                category=args.category,
                enabled=not args.disabled,
            )
            state = "выключенным" if not source.enabled else "включённым"
            print(f"Добавлен источник {source.source_id} ({state}): {source.url}")
            return 0
        if action in {"rm", "remove", "del"}:
            source = remove_source(args.config, args.identifier)
            print(f"Удалён источник {source.source_id}: {source.url}")
            return 0
        if action in {"on", "enable"}:
            source = set_source_enabled(args.config, args.identifier, True)
            print(f"Источник {source.source_id} включён")
            return 0
        if action in {"off", "disable"}:
            source = set_source_enabled(args.config, args.identifier, False)
            print(f"Источник {source.source_id} выключен")
            return 0
    except (ConfigError, OSError) as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1
    parser.print_help()
    return 1


def _run_build(argv: Sequence[str] | None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    try:
        config = load_config(args.config)
        with process_lock(config.paths.stats.parent / ".vpnmy.lock"):
            report = build_subscription(
                config, skip_deep_check=args.skip_deep_check, dry_run=args.dry_run
            )
    except (ConfigError, BuildError, XrayError, OSError, ValueError) as exc:
        logging.getLogger(__name__).error("Сборка остановлена: %s", exc)
        return 1
    summary = (
        f"Источники: {report.sources_ok}/{report.sources_total}; конфигурации: {report.parsed}; "
        f"TCP: {report.probed}; Xray/проверено: {report.verified}; опубликовано: {report.published}; статус: {report.status}."
    )
    logging.getLogger(__name__).info(summary)
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        try:
            with Path(github_summary).open("a", encoding="utf-8") as handle:
                handle.write("## Результат обновления FL1P VPN\n\n")
                handle.write(f"- {summary}\n")
                handle.write(f"- Режим проверки: `{report.check_mode}`\n")
        except OSError as exc:
            logging.getLogger(__name__).warning("Не удалось записать Job Summary: %s", exc)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "sources" in args:
        index = args.index("sources")
        return _run_sources(args[:index] + args[index + 1 :])
    if "--help" in args or "-h" in args:
        _parser().parse_args(args)
        return 0
    return _run_build(args)

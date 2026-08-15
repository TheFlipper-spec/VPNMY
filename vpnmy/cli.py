from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .builder import BuildError, build_subscription
from .config import ConfigError, load_config
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
        description="Собирает и проверяет публичную VPN-подписку для пользователей из России."
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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

"""Распределение глубокой проверки между ядрами Xray и Hysteria."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from typing import Any

from . import hysteria, xray
from .models import CheckResult, Node, ProbeResult

LOGGER = logging.getLogger(__name__)


def verify_all(
    probes: list[ProbeResult],
    *,
    xray_bin: str,
    hysteria_bin: str | None,
    timeout: float,
    speed_test_bytes: int,
    workers: int,
) -> tuple[list[CheckResult], list[Node], list[Node]]:
    """Проверяет узлы подходящим ядром.

    Возвращает (успешные, провалившиеся, пропущенные). Пропущенные — это
    Hysteria2-узлы при отсутствии клиента Hysteria: они не засчитываются
    как отказ в истории.
    """
    verified: list[CheckResult] = []
    failed: list[Node] = []
    skipped: list[Node] = []
    hy_probes = [probe for probe in probes if probe.node.is_hysteria]
    classic_probes = [probe for probe in probes if not probe.node.is_hysteria]
    if hy_probes and not hysteria_bin:
        LOGGER.warning(
            "Клиент Hysteria не найден: %d hysteria2-узлов пропущены", len(hy_probes)
        )
        skipped.extend(probe.node for probe in hy_probes)
        hy_probes = []

    tasks: list[tuple[ProbeResult, Callable[[], Any]]] = [
        *(
            (
                probe,
                partial(
                    xray.verify_node,
                    probe,
                    xray_bin=xray_bin,
                    timeout=timeout,
                    speed_test_bytes=speed_test_bytes,
                ),
            )
            for probe in classic_probes
        ),
        *(
            (
                probe,
                partial(
                    hysteria.verify_node,
                    probe,
                    hysteria_bin=hysteria_bin or "",
                    timeout=timeout,
                    speed_test_bytes=speed_test_bytes,
                ),
            )
            for probe in hy_probes
        ),
    ]
    if not tasks:
        return verified, failed, skipped
    with ThreadPoolExecutor(
        max_workers=min(workers, len(tasks)), thread_name_prefix="core"
    ) as executor:
        futures = {executor.submit(fn): probe.node for probe, fn in tasks}
        for future in as_completed(futures):
            node = futures[future]
            try:
                result = future.result()
            except Exception:  # pragma: no cover - страховка отдельного worker
                LOGGER.exception("Непредвиденная ошибка проверки узла %s", node.node_id)
                result = None
            if result is None:
                failed.append(node)
            else:
                verified.append(result)
    verified.sort(key=lambda item: (item.http_ms, item.node.node_id))
    LOGGER.info(
        "Глубокая проверка (Xray/Hysteria): работают %d из %d узлов, пропущено %d",
        len(verified),
        len(tasks),
        len(skipped),
    )
    return verified, failed, skipped

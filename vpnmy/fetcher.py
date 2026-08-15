from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Source

LOGGER = logging.getLogger(__name__)
_MAX_SOURCE_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class FetchResult:
    source: Source
    text: str | None
    elapsed_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.text is not None


def _session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": "FL1P-VPN-Subscription/2.1 (+https://github.com/TheFlipper-spec/VPNMY)",
            "Accept": "text/plain, application/octet-stream;q=0.9, */*;q=0.1",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    return session


def fetch_source(source: Source, timeout: float) -> FetchResult:
    started = time.monotonic()
    try:
        with (
            _session() as session,
            session.get(
                source.url, timeout=(5.0, timeout), stream=True, allow_redirects=True
            ) as response,
        ):
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            if length and int(length) > _MAX_SOURCE_BYTES:
                raise ValueError("ответ превышает 8 МБ")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_SOURCE_BYTES:
                    raise ValueError("ответ превышает 8 МБ")
                chunks.append(chunk)
            content = b"".join(chunks)
            encoding = (
                response.encoding
                if response.encoding and response.encoding.lower() != "iso-8859-1"
                else "utf-8"
            )
            text = content.decode(encoding, errors="replace")
        return FetchResult(source, text, int((time.monotonic() - started) * 1000))
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        return FetchResult(
            source, None, int((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {exc}"
        )


def fetch_all(sources: tuple[Source, ...], timeout: float, workers: int) -> list[FetchResult]:
    enabled = [source for source in sources if source.enabled]
    results: list[FetchResult] = []
    with ThreadPoolExecutor(
        max_workers=min(workers, len(enabled)), thread_name_prefix="source"
    ) as executor:
        futures = {executor.submit(fetch_source, source, timeout): source for source in enabled}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result.ok:
                LOGGER.info(
                    "Источник «%s» загружен за %d мс", result.source.name, result.elapsed_ms
                )
            else:
                LOGGER.warning("Источник «%s» недоступен: %s", result.source.name, result.error)
    results.sort(key=lambda item: item.source.source_id)
    return results

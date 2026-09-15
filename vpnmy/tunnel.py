"""Общая логика глубокой проверки через локальный SOCKS5-туннель ядра.

И Xray, и официальный клиент Hysteria поднимают локальный SOCKS5-inbound;
дальше проверка одинаковая: Cloudflare trace, независимое подтверждение
открытого интернета и короткий замер скорости.

Измерение задержки
------------------
* Базовое измерение — время одного GET ``TRACE_URL`` (по умолчанию Cloudflare trace)
  через SOCKS5-туннель ядра. Измеряется интервал от ``perf_counter`` до получения
  статуса и тела ответа, включая SOCKS-рукопожатие, QUIC/TLS-рукопожатие внутри
  туннеля и сетевой RTT. DNS самого trace-хоста резолвится транзитом через туннель
  (``socks5h``), а не локально.
* Каждая попытка измерения использует **свежий** ``requests.Session`` (``trust_env=False``),
  поэтому повторное использование TCP/TLS-соединения **между попытками не влияет**
  на медиану: каждая попытка стартует с холодного SOCKS-подключения. Внутри одной
  попытки trace и подтверждающий запрос могут переиспользовать соединение — это
  намеренно, так как измеряемой величиной считается именно trace-задержка, а
  подтверждение лишь валидирует, что трафик действительно прошёл через туннель.
* При ``attempts=N`` (по умолчанию 3) выполняются N независимых попыток
  ``trace + подтверждение`` через один и тот же туннель (ядро уже запущено).
  Успешной считается попытка, где trace вернул глобальный IP и валидный ``loc``,
  а подтверждающий запрос (``generate_204`` или ``success.txt``) прошёл.
* Неудачные попытки (таймаут, HTTP-ошибка, невалидный trace) **не отбрасываются**:
  их задержка учитывается как ``timeout*1000`` мс при расчёте медианы/максимума/
  разброса. Это предотвращает ситуацию, когда один удачный замер на фоне двух
  таймаутов выглядит «быстрым».
* Для каждой серии считаются:
  - ``median_ms`` — медиана всех N задержек (включая таймауты как значения);
  - ``max_ms`` — худший результат;
  - ``jitter_ms`` — разброс ``max - min``.
  Стабильный узел ``650/700/680`` (медиана 680, разброс 50) получает более высокий
  скор, чем нестабильный ``400/450/3800`` (медиана 450, разброс 3400, max 3800),
  несмотря на меньшую медиану, — за счёт штрафа за разброс и максимум.
* Скорость измеряется **один раз** на успешной попытке, чтобы не утраивать трафик
  (``speed_test_bytes`` скачивается только один раз, а не N раз).
* Порог медианы по умолчанию 1500 мс: узел с медианой выше считается слишком
  медленным и фильтруется на этапе отбора.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import statistics
import subprocess
import time

import requests

TRACE_URL = os.environ.get("VPNMY_TRACE_URL", "https://www.cloudflare.com/cdn-cgi/trace")
SPEED_URL = os.environ.get("VPNMY_SPEED_URL", "https://speed.cloudflare.com/__down?bytes={n}")
CONFIRMATION_TARGETS = (
    ("https://www.gstatic.com/generate_204", frozenset({204}), None),
    ("https://detectportal.firefox.com/success.txt", frozenset({200}), "success"),
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_inbound(process: subprocess.Popen[bytes], port: int, timeout: float = 2.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def parse_trace(body: str) -> tuple[str, str] | None:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and key not in fields:
            fields[key] = value.strip()
    try:
        exit_ip = ipaddress.ip_address(fields.get("ip", ""))
    except ValueError:
        return None
    country = fields.get("loc", "").upper()
    if not exit_ip.is_global or not re.fullmatch(r"[A-Z]{2}", country):
        return None
    return exit_ip.compressed, country


def _confirm_open_internet(session: requests.Session, proxies: dict[str, str], timeout: float) -> bool:
    """Второй, независимый от Cloudflare trace HTTPS-запрос через туннель."""
    request_timeout = (3.0, min(timeout, 6.0))
    for url, expected_statuses, expected_body in CONFIRMATION_TARGETS:
        try:
            with session.get(
                url,
                proxies=proxies,
                timeout=request_timeout,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code not in expected_statuses:
                    continue
                if expected_body is None:
                    return True
                body = next(response.iter_content(chunk_size=64), b"")
                if body.decode("utf-8", errors="replace").strip() == expected_body:
                    return True
        except requests.RequestException:
            continue
    return False


def http_checks(
    session: requests.Session,
    proxies: dict[str, str],
    *,
    timeout: float,
    speed_test_bytes: int,
    logger=None,
    node_id: str = "",
) -> tuple[int, str, float] | None:
    """Совместимость: одиночная проверка (эквивалент attempts=1).

    В новом коде используется :func:`http_checks_multi` с медианой.
    Возвращает (http_ms, country, speed_mbps) или None.
    """
    result = http_checks_multi(
        proxies,
        timeout=timeout,
        speed_test_bytes=speed_test_bytes,
        attempts=1,
        logger=logger,
        node_id=node_id,
    )
    if result is None:
        return None
    median_ms, _max_ms, _jitter_ms, country, _egress_ip, speed_mbps, _succ, _samples = result
    return median_ms, country, speed_mbps


def http_checks_multi(
    proxies: dict[str, str],
    *,
    timeout: float,
    speed_test_bytes: int,
    attempts: int = 3,
    logger=None,
    node_id: str = "",
    user_agent: str = "FL1P-VPN-Healthcheck/2.3",
) -> tuple[int, int, int, str, str, float, int, tuple[int, ...]] | None:
    """Серия измерений через туннель.

    Выполняет *attempts* независимых попыток ``trace + подтверждение``,
    каждая на свежем ``Session`` (холодное соединение). Первое успешное
    подтверждение даёт ``egress_ip`` и ``country``. Скорость меряется один раз.

    Возвращает кортеж:
    ``(median_ms, max_ms, jitter_ms, country, egress_ip, speed_mbps,
    success_count, samples)``,
    где ``samples`` — все N задержек (неудачи = int(timeout*1000)).
    Если ни одна попытка не подтвердилась — ``None``.

    Требует минимум две независимые HTTPS-проверки на каждую попытку:
    trace и confirmation. Ошибки/таймауты не отбрасываются, а входят в медиану.
    """
    if attempts < 1:
        attempts = 1
    timeout_ms = max(1, int(timeout * 1000))
    samples: list[int] = []
    egress_ip = ""
    country = ""
    success_count = 0
    # Для country/egress берём первый успех (или большинство — но первый детерминирован).
    first_success_country = ""
    first_success_egress = ""

    for _ in range(attempts):
        session = make_session(user_agent)
        try:
            started = time.perf_counter()
            try:
                response = session.get(TRACE_URL, proxies=proxies, timeout=(3.0, timeout))
                response.raise_for_status()
                body = response.text[:16_384]
                http_ms = max(1, round((time.perf_counter() - started) * 1000))
                trace = parse_trace(body)
            except requests.RequestException:
                # Таймаут/сетевая ошибка — считаем как timeout_ms
                samples.append(timeout_ms)
                continue
            if trace is None:
                samples.append(timeout_ms)
                continue
            ip, loc = trace
            if not _confirm_open_internet(session, proxies, timeout):
                samples.append(timeout_ms)
                continue
            # Успех
            samples.append(http_ms)
            success_count += 1
            if not first_success_egress:
                first_success_egress = ip
                first_success_country = loc
        finally:
            session.close()

    if success_count == 0:
        return None
    # Для медианы учитываем и таймауты как значения — уже в samples.
    # Если successes < attempts, медиана может быть завышена, но jitter покажет нестабильность.
    median_ms = int(statistics.median(samples))
    max_ms = max(samples)
    jitter_ms = max_ms - min(samples)
    egress_ip = first_success_egress
    country = first_success_country

    # Скорость — один раз, на свежем соединении через тот же туннель, если есть успех.
    speed_mbps = 0.0
    if speed_test_bytes > 0 and success_count > 0:
        session = make_session(user_agent)
        try:
            try:
                speed_started = time.perf_counter()
                downloaded = 0
                with session.get(
                    SPEED_URL.format(n=speed_test_bytes),
                    proxies=proxies,
                    timeout=(3.0, timeout),
                    stream=True,
                ) as speed_response:
                    speed_response.raise_for_status()
                    for chunk in speed_response.iter_content(chunk_size=64 * 1024):
                        downloaded += len(chunk)
                elapsed = time.perf_counter() - speed_started
                if downloaded and elapsed > 0:
                    speed_mbps = round(downloaded * 8 / 1_000_000 / elapsed, 2)
            except requests.RequestException:
                if logger is not None:
                    logger.debug("Замер скорости недоступен для узла %s", node_id)
        finally:
            session.close()
    return median_ms, max_ms, jitter_ms, country, egress_ip, speed_mbps, success_count, tuple(samples)


def make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = user_agent
    return session

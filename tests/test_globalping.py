"""Тесты российской проверки через Globalping (асинхронный клиент + интеграция)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import vpnmy.builder as builder
import vpnmy.globalping as gp
from vpnmy.builder import BuildError, build_subscription
from vpnmy.config import BuildConfig, Paths, load_config
from vpnmy.fetcher import FetchResult
from vpnmy.models import CheckResult, ProbeResult, Source
from vpnmy.parser import parse_source

# ---------------------------------------------------------------- фикстуры


def make_source():
    return Source("test", "Тест", "https://example.com/sub", "universal")


def make_node(host="1.1.1.1", port=443, hy=False, name="node"):
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    if hy:
        link = f"hysteria2://u:p@{host}:{port}?insecure=1&sni=x.com#{name}"
    else:
        link = (
            f"vless://{uuid}@{host}:{port}"
            f"?encryption=none&security=tls&type=ws&sni=x.com#{name}"
        )
    nodes, _rejected = parse_source(link, make_source())
    assert nodes, "парсер должен принять тестовый узел"
    return nodes[0]


def probe(node, ms=20, resolved_ip=""):
    return ProbeResult(node, ms, resolved_ip or "")


def finished_payload(rtt_groups, country="RU", node_id="m1"):
    """Готовый результат измерения: rtt_groups — список RTT по каждому проблу."""
    results = []
    for rtts in rtt_groups:
        timings = [{"rtt": r} for r in rtts]
        results.append(
            {
                "probe": {"country": country, "asn": 12345},
                "result": {
                    "status": "finished",
                    "resolvedAddress": "1.2.3.4",
                    "timings": timings,
                    "stats": {
                        "min": min(rtts) if rtts else None,
                        "max": max(rtts) if rtts else None,
                        "avg": (sum(rtts) / len(rtts)) if rtts else None,
                        "total": 2,
                        "rcv": len(rtts),
                        "drop": 0,
                        "loss": 0 if rtts else 100,
                    },
                },
            }
        )
    return {"id": node_id, "status": "finished", "results": results}


def in_progress_payload(node_id="m1"):
    return {"id": node_id, "status": "in-progress"}


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def text(self, errors=None):
        return json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Двойник aiohttp.ClientSession: request() -> async-контекст с ответом."""

    def __init__(self, handler, **kwargs):
        self.handler = handler
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def request(self, method, url, json=None):
        self.calls.append((method, url, json))
        return self.handler(method, url, json)


def install_fake_session(monkeypatch, handler):
    """Подменяет aiohttp.ClientSession для _run; возвращает список сессий."""
    import aiohttp

    sessions = []

    def factory(**kwargs):
        session = FakeSession(handler)
        sessions.append(session)
        return session

    monkeypatch.setattr(aiohttp, "ClientSession", factory)
    return sessions


def patch_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return sleeps


def run_coro(coro):
    return asyncio.run(coro)


def run_ru(monkeypatch, probes, handler, *, budget=10, concurrency=12, deadline=60.0):
    sessions = install_fake_session(monkeypatch, handler)
    patch_sleep(monkeypatch)
    results, stats = run_coro(
        gp._run(
            [p for p in probes],
            token="t",
            checked_at="2026-09-20T00:00:00Z",
            budget=budget,
            concurrency=concurrency,
            probes_per_target=3,
            packets=2,
            poll_interval=0.55,
            deadline_seconds=deadline,
        )
    )
    return results, stats, sessions


LIMITS_OK = {
    "rateLimit": {
        "measurements": {
            "create": {"type": "user", "limit": 250, "remaining": 240, "reset": 100}
        }
    }
}


def limits_then_post_create_poll(
    polls_by_id, create_payload=None, create_headers=None, limits_payload=LIMITS_OK
):
    """Обработчик: GET /v1/limits → 202 на создание → N поллингов до finished."""
    state = {"polls": 0}

    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, limits_payload)
        if method == "POST" and url.endswith("/v1/measurements"):
            state["polls"] = 0
            payload = create_payload or {"id": "m1"}
            return FakeResponse(202, payload, headers=create_headers or {})
        if method == "GET" and "/v1/measurements/" in url:
            mid = url.rsplit("/", 1)[-1]
            polls = polls_by_id.get(mid, [])
            index = min(state["polls"], len(polls) - 1)
            state["polls"] += 1
            return FakeResponse(200, polls[index])
        return FakeResponse(404, {"error": {"type": "not_found"}})

    return handler


# ------------------------------------------------------------------ парсинг


def test_parse_measurement_success():
    total, ok, latency, countries = gp.parse_measurement(finished_payload([[40.0, 42.0], [50.0]]))
    assert total == 2 and ok == 2
    assert latency == 42  # медиана [40, 42, 50]
    assert countries == ("RU",)


def test_parse_measurement_all_failed():
    total, ok, latency, _countries = gp.parse_measurement(finished_payload([[], []]))
    assert total == 2 and ok == 0 and latency is None


def test_parse_measurement_stats_fallback():
    payload = {
        "results": [
            {
                "probe": {"country": "RU"},
                "result": {
                    "status": "finished",
                    "timings": [],
                    "stats": {"rcv": 1, "loss": 50, "avg": 33.5},
                },
            }
        ]
    }
    total, ok, latency, _c = gp.parse_measurement(payload)
    assert total == 1 and ok == 1 and latency == 34


def test_parse_measurement_malformed():
    assert gp.parse_measurement({}) == (0, 0, None, ())
    assert gp.parse_measurement({"results": [None, "x", {"probe": {}, "result": {}}]})[0] == 1


def test_decide_verdict():
    assert gp.decide_verdict("tcp", 3, 2) == (True, "")
    assert gp.decide_verdict("tcp", 2, 0) == (False, "blocked")
    assert gp.decide_verdict("tcp", 1, 0)[0] is None  # один проб — слабый сигнал
    assert gp.decide_verdict("icmp", 2, 0) == (None, "icmp_silent")
    assert gp.decide_verdict("icmp", 0, 0) == (None, "no_results")


def test_order_for_check_priority():
    a, b, c, d = (make_node(f"1.1.1.{i}") for i in range(4))
    pa, pb, pc, pd = (probe(n, ms) for n, ms in ((a, 30), (b, 10), (c, 50), (d, 20)))
    shortlisted = [pc, pa]
    ordered = gp.order_for_check([pa, pb, pc, pd], shortlisted, published_ids={d.node_id})
    assert ordered[0].node is d  # опубликованный — первый
    assert ordered[1].node is c  # затем shortlist в своём порядке
    assert ordered[2].node is a
    assert ordered[3].node is b  # остальные по локальному пингу


def test_load_published_ids(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"servers": [{"id": "x1"}, {"id": "x2"}, "broken"]}))
    assert gp.load_published_ids(path) == {"x1", "x2"}
    assert gp.load_published_ids(tmp_path / "missing.json") == set()


def test_record_ru_result(tmp_path):
    history = {"schema_version": 1, "nodes": {}}
    rid = "n1"
    ok_res = gp.RuProbeResult(rid, True, "tcp", 42, 3, 3)
    gp.record_ru_result(history, rid, ok_res, "T1")
    row = history["nodes"][rid]
    assert row["ru_ms"] == 42 and row["ru_ok_at"] == "T1" and row["ru_blocked_streak"] == 0
    gp.record_ru_result(history, rid, gp.RuProbeResult(rid, False, "tcp", reason="blocked"), "T2")
    assert row["ru_blocked"] is True and row["ru_blocked_streak"] == 1 and row["ru_ms"] is None
    gp.record_ru_result(history, rid, gp.RuProbeResult(rid, False, "tcp", reason="blocked"), "T3")
    assert row["ru_blocked_streak"] == 2


def test_is_enabled(monkeypatch):
    class _Cfg:
        ru_check_enabled = None

    monkeypatch.delenv("GLOBALPING_TOKEN", raising=False)
    enabled, reason = gp.is_enabled(_Cfg())
    assert enabled is False and "GLOBALPING_TOKEN" in reason
    monkeypatch.setenv("GLOBALPING_TOKEN", "tok")
    assert gp.is_enabled(_Cfg()) == (True, "")
    _Cfg.ru_check_enabled = False
    assert gp.is_enabled(_Cfg())[0] is False


def test_run_ru_check_disabled_without_token(monkeypatch):
    monkeypatch.delenv("GLOBALPING_TOKEN", raising=False)

    class _Cfg:
        ru_check_enabled = None

    results, stats = gp.run_ru_check([], None, frozenset(), _Cfg(), checked_at="T")
    assert results == {} and stats.enabled is False and stats.reason


# ------------------------------------------------------------------ клиент


def test_client_success_flow(monkeypatch):
    handler = limits_then_post_create_poll(
        {"m1": [in_progress_payload(), finished_payload([[40, 42], [50]])]}
    )
    results, stats, _sessions = run_ru(monkeypatch, [probe(make_node("9.9.9.9"))], handler)
    (result,) = results.values()
    assert result.ok is True and result.kind == "tcp"
    assert result.latency_ms == 42 and result.probes_total == 2 and result.probes_ok == 2
    assert stats.submitted == 1 and stats.checked == 1 and stats.reachable == 1
    assert stats.median_latency_ms == 42
    assert stats.quota_remaining == 240


def test_client_blocked_verdict(monkeypatch):
    handler = limits_then_post_create_poll({"m1": [finished_payload([[], []])]})
    results, stats, _sessions = run_ru(monkeypatch, [probe(make_node("9.9.9.9"))], handler)
    (result,) = results.values()
    assert result.ok is False and result.reason == "blocked"
    assert stats.blocked == 1 and stats.unknown == 0


def test_client_hysteria_icmp_silent(monkeypatch):
    handler = limits_then_post_create_poll({"m1": [finished_payload([[], []])]})
    results, stats, _sessions = run_ru(monkeypatch, [probe(make_node("9.9.9.9", hy=True))], handler)
    (result,) = results.values()
    assert result.kind == "icmp"
    assert result.ok is None and result.reason == "icmp_silent"  # не «блокировка»
    assert stats.unknown == 1


def test_client_429_retries_with_retry_after(monkeypatch):
    state = {"posts": 0, "polls": 0}
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            state["posts"] += 1
            if state["posts"] == 1:
                return FakeResponse(
                    429,
                    {
                        "error": {
                            "type": "too_many_requests",
                            "message": "Too many requests. Please retry in 2 seconds.",
                        }
                    },
                )
            return FakeResponse(202, {"id": "m1"})
        state["polls"] += 1
        if state["polls"] == 1:
            return FakeResponse(200, in_progress_payload("m1"))
        return FakeResponse(200, finished_payload([[10]]))

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kw: FakeSession(handler))
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    results, stats = run_coro(
        gp._run(
            [probe(make_node())],
            token="t",
            checked_at="T",
            budget=1,
            concurrency=1,
            probes_per_target=3,
            packets=2,
            poll_interval=0.55,
            deadline_seconds=60,
        )
    )
    assert stats.rate_limited == 1 and state["posts"] == 2
    assert 1.9 <= sleeps[0] <= 2.1  # «retry in 2 seconds» из тела 429
    assert next(iter(results.values())).ok is True


def test_client_500_retries_with_backoff(monkeypatch):
    state = {"posts": 0}
    patched_sleeps = []

    async def fake_sleep(delay):
        patched_sleeps.append(delay)

    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            state["posts"] += 1
            if state["posts"] == 1:
                return FakeResponse(500, {"error": "boom"})
            return FakeResponse(202, {"id": "m1"})
        return FakeResponse(200, finished_payload([[10]]))

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kw: FakeSession(handler))
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    results, stats = run_coro(
        gp._run(
            [probe(make_node())],
            token="t",
            checked_at="T",
            budget=1,
            concurrency=1,
            probes_per_target=3,
            packets=2,
            poll_interval=0.55,
            deadline_seconds=60,
        )
    )
    assert state["posts"] == 2 and stats.retries >= 1
    assert next(iter(results.values())).ok is True
    assert patched_sleeps and 0.5 <= patched_sleeps[0] <= 1.0  # backoff ~1с с джиттером


def test_client_422_no_ru_probes(monkeypatch):
    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            return FakeResponse(
                422,
                {
                    "error": {
                        "type": "no_probes_found",
                        "message": "No matching IPv4 probes available.",
                    }
                },
            )
        return FakeResponse(404, {})

    results, stats, _sessions = run_ru(monkeypatch, [probe(make_node())], handler)
    (result,) = results.values()
    assert result.ok is None and result.reason == "no_ru_probes"
    assert stats.no_probes == 1 and stats.submitted == 0


def test_client_quota_exhausted(monkeypatch):
    limits = {"rateLimit": {"measurements": {"create": {"type": "user", "remaining": 2}}}}
    handler = limits_then_post_create_poll({}, limits_payload=limits)
    results, stats, sessions = run_ru(
        monkeypatch, [probe(make_node(f"1.1.1.{i}")) for i in range(3)], handler
    )
    assert stats.budget == 0 and stats.reason
    assert all(r.ok is None and r.reason == "quota_exhausted" for r in results.values())
    assert stats.not_checked == 3
    # POST-запросов на создание измерений не было вовсе
    posts = [c for s in sessions for c in s.calls if c[0] == "POST"]
    assert posts == []


def test_endpoint_dedup_shares_measurement(monkeypatch):
    """Две конфигурации одного IP:port — одно измерение, вердикт у обоих узлов."""
    handler = limits_then_post_create_poll({"m1": [finished_payload([[10]])]})
    link_a = "vless://123e4567-e89b-12d3-a456-426614174000@5.5.5.5:443?encryption=none&security=tls&type=ws&sni=x.com#A"
    link_b = "vless://123e4567-e89b-12d3-a456-426614174099@5.5.5.5:443?encryption=none&security=tls&type=ws&sni=x.com#B"
    node_a = parse_source(link_a, make_source())[0][0]
    node_b = parse_source(link_b, make_source())[0][0]
    assert node_a.node_id != node_b.node_id  # разные креды — разные узлы
    results, stats, _sessions = run_ru(
        monkeypatch, [probe(node_a), probe(node_b)], handler, budget=1
    )
    assert stats.submitted == 1  # одно измерение на endpoint
    assert len(results) == 2
    assert all(r.ok is True for r in results.values())
    assert stats.reachable == 2


def test_client_budget_cap(monkeypatch):
    handler = limits_then_post_create_poll({"m1": [finished_payload([[10]])]})
    nodes = [probe(make_node(f"1.1.1.{i}")) for i in range(5)]
    results, stats, _sessions = run_ru(monkeypatch, nodes, handler, budget=2)
    assert stats.budget == 2
    checked = [r for r in results.values() if r.ok is True]
    not_checked = [r for r in results.values() if r.reason == "budget"]
    assert len(checked) == 2 and len(not_checked) == 3


def test_client_stops_on_credits(monkeypatch):
    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            return FakeResponse(
                202,
                {"id": "m1"},
                headers={"X-Credits-Consumed": "1", "X-Request-Cost": "1"},
            )
        return FakeResponse(200, finished_payload([[10]]))

    results, stats, _sessions = run_ru(
        monkeypatch,
        [probe(make_node(f"1.1.1.{i}")) for i in range(3)],
        handler,
        budget=3,
        concurrency=1,
    )
    assert stats.credits_seen == 1 and stats.submitted == 1  # дальше ничего не создали
    reasons = sorted(r.reason for r in results.values())
    assert reasons.count("quota_exhausted") == 2


def test_client_polling_deadline(monkeypatch):
    handler = limits_then_post_create_poll({"m1": [in_progress_payload()] * 100})
    results, stats, _sessions = run_ru(monkeypatch, [probe(make_node())], handler, deadline=0.5)
    (result,) = results.values()
    # Измерение создано, но до финального состояния не дошло:
    # это ошибка API (api_errors), а не «неизвестный вердикт».
    assert result.ok is None and result.reason == "poll_timeout"
    assert stats.submitted == 1 and stats.api_errors == 1 and stats.checked == 0


def test_tcp_body_shape(monkeypatch):
    """Тело запроса: ping + TCP + порт + locations RU."""
    captured = {}

    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            captured["body"] = json
            return FakeResponse(202, {"id": "m1"})
        return FakeResponse(200, finished_payload([[10]]))

    install_fake_session(monkeypatch, handler)
    patch_sleep(monkeypatch)
    run_coro(
        gp._run(
            [probe(make_node("7.7.7.7", port=8443))],
            token="t",
            checked_at="T",
            budget=1,
            concurrency=1,
            probes_per_target=4,
            packets=2,
            poll_interval=0.55,
            deadline_seconds=60,
        )
    )
    body = captured["body"]
    assert body["type"] == "ping"
    assert body["target"] == "7.7.7.7"
    assert body["locations"] == [{"country": "RU"}]
    assert body["limit"] == 4
    assert body["measurementOptions"] == {"packets": 2, "protocol": "TCP", "port": 8443}


def test_hysteria_uses_icmp(monkeypatch):
    captured = {}

    def handler(method, url, json=None):
        if method == "GET" and url.endswith("/v1/limits"):
            return FakeResponse(200, LIMITS_OK)
        if method == "POST":
            captured["body"] = json
            return FakeResponse(202, {"id": "m1"})
        return FakeResponse(200, finished_payload([[10]]))

    install_fake_session(monkeypatch, handler)
    patch_sleep(monkeypatch)
    run_coro(
        gp._run(
            [probe(make_node("7.7.7.7", port=9000, hy=True))],
            token="t",
            checked_at="T",
            budget=1,
            concurrency=1,
            probes_per_target=3,
            packets=2,
            poll_interval=0.55,
            deadline_seconds=60,
        )
    )
    assert captured["body"]["measurementOptions"] == {"packets": 2, "protocol": "ICMP"}
    assert "port" not in captured["body"]["measurementOptions"]


def test_run_async_from_running_loop():
    """run_async работает и внутри уже запущенного цикла (фоновый поток)."""

    async def inside():
        async def coro():
            await asyncio.sleep(0)
            return 42

        return gp.run_async(coro())

    assert asyncio.run(inside()) == 42


# ------------------------------------------------------------------ сборка


def cfg(tmp_path, countries_file):
    ss = (
        Source("u", "U", "https://x/u", "universal"),
        Source("w", "W", "https://x/w", "whitelist"),
    )
    p = Paths(
        tmp_path / "b64",
        tmp_path / "raw",
        tmp_path / "stats",
        tmp_path / "hist",
        countries_file,
    )
    return BuildConfig(
        ss,
        p,
        3,
        3,
        10,
        1,
        {"universal": 2, "whitelist": 1},
        ("DE", "RU"),
        2,
        2,
        2,
        5,
        1,
        5,
        0,
        "xray",
    )


def four_links():
    hosts = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
    return [
        f"vless://123e4567-e89b-12d3-a456-42661417400{i}@{hosts[i]}:443"
        f"?encryption=none&security=tls&type=ws&sni=x.com#N{i}"
        for i in range(4)
    ]


def wire_build(monkeypatch, links):
    monkeypatch.setattr(builder, "resolve_xray", lambda _: "x")
    monkeypatch.setattr(builder, "resolve_hysteria", lambda _: "hy")

    def fake_fetch(sources, t, w):
        out = []
        for s in sources:
            if s.category == "universal":
                out.append(FetchResult(s, "\n".join(links[:3]), 1))
            else:
                out.append(FetchResult(s, links[3], 1))
        return out

    monkeypatch.setattr(builder, "fetch_all", fake_fetch)
    monkeypatch.setattr(
        builder, "probe_all", lambda ns, tcp, udp, w: [ProbeResult(n, 20) for n in ns]
    )


def fake_verify(monkeypatch, collected):
    def fake_verify_all(ps, **kw):
        collected.extend(p.node.node_id for p in ps)
        return (
            [
                CheckResult(p.node, 20, 50, 10, "DE", "2026-01-01T00:00:00Z", checks_passed=2)
                for p in ps
            ],
            [],
            [],
        )

    monkeypatch.setattr(builder, "verify_all", fake_verify_all)


def test_builder_ru_blocked_excluded(tmp_path, countries_file, monkeypatch):
    c = cfg(tmp_path, countries_file)
    links = four_links()
    wire_build(monkeypatch, links)
    verified = []
    fake_verify(monkeypatch, verified)

    nodes_by_link = {}
    for link in links:
        nodes, _ = parse_source(link, make_source())
        nodes_by_link[link] = nodes[0]
    blocked_node = nodes_by_link[links[1]]

    def fake_ru(probes, shortlisted, published_ids, config, *, checked_at):
        results = {
            p.node.node_id: gp.RuProbeResult(p.node.node_id, True, "tcp", 42, 3, 3)
            for p in probes
        }
        results[blocked_node.node_id] = gp.RuProbeResult(
            blocked_node.node_id, False, "tcp", reason="blocked"
        )
        stats = gp.RuCheckStats(
            enabled=True, budget=4, configured_budget=4, checked=4, reachable=3, blocked=1
        )
        return results, stats

    monkeypatch.setattr(builder.globalping, "run_ru_check", fake_ru)
    report = build_subscription(c, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert blocked_node.node_id not in verified  # не ушёл на глубокую проверку
    stats = json.loads(c.paths.stats.read_text())
    assert stats["ru_check"]["enabled"] is True
    assert stats["ru_check"]["blocked"] == 1
    assert report.ru_summary
    history = json.loads(c.paths.history.read_text())
    row = history["nodes"][blocked_node.node_id]
    assert row["failures"] == 1 and row["ru_blocked"] is True
    # у опубликованных серверов есть ru_ms
    published_ids = {s["id"] for s in stats["servers"]}
    assert blocked_node.node_id not in published_ids
    assert any(s.get("ru_ms") == 42 for s in stats["servers"])


def test_builder_ru_all_blocked_failsafe(tmp_path, countries_file, monkeypatch):
    c = cfg(tmp_path, countries_file)
    c.paths.subscription_base64.write_text("old")
    links = four_links()
    wire_build(monkeypatch, links)
    verified = []
    fake_verify(monkeypatch, verified)

    def fake_ru(probes, shortlisted, published_ids, config, *, checked_at):
        results = {
            p.node.node_id: gp.RuProbeResult(p.node.node_id, False, "tcp", reason="blocked")
            for p in probes
        }
        return results, gp.RuCheckStats(enabled=True, budget=4, blocked=4)

    monkeypatch.setattr(builder.globalping, "run_ru_check", fake_ru)
    with pytest.raises(BuildError, match="российской сети"):
        build_subscription(c, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert verified == []
    assert c.paths.subscription_base64.read_text() == "old"  # подписка не затёрта


def test_builder_ru_disabled_without_token(tmp_path, countries_file, monkeypatch):
    """Без токена этап честно пропускается, сборка работает как раньше."""
    monkeypatch.delenv("GLOBALPING_TOKEN", raising=False)
    c = cfg(tmp_path, countries_file)
    links = four_links()
    wire_build(monkeypatch, links)
    verified = []
    fake_verify(monkeypatch, verified)
    report = build_subscription(c, now=datetime(2026, 1, 1, tzinfo=UTC))
    stats = json.loads(c.paths.stats.read_text())
    assert stats["ru_check"]["enabled"] is False
    assert "GLOBALPING_TOKEN" in stats["ru_check"]["reason"]
    assert report.ru_summary.startswith("пропущена")
    assert len(verified) == 4  # все узлы ушли на глубокую проверку


def test_builder_with_token_uses_mocked_ru_layer(tmp_path, countries_file, monkeypatch):
    """CI-сценарий из update.yml: токен в окружении — сборка должна пройти

    RU-этап (is_enabled → run_ru_check → _run) без обращения к сети.
    Регрессия: ранее тесты test_builder без этой изоляции ходили в
    настоящий Globalping API по тестовым IP, и CI падал в зависимости
    от того, какие порты на этих IP реально открыты.
    """
    monkeypatch.setenv("GLOBALPING_TOKEN", "ci-fake-token")  # перезаписывает delenv conftest
    c = cfg(tmp_path, countries_file)
    links = four_links()
    wire_build(monkeypatch, links)
    verified = []
    fake_verify(monkeypatch, verified)

    seen = {}

    async def fake_run(ordered, **kwargs):
        seen["token"] = kwargs.get("token")
        seen["count"] = len(ordered)
        results = {
            p.node.node_id: gp.RuProbeResult(p.node.node_id, True, "tcp", 42, 3, 3)
            for p in ordered
        }
        stats = gp.RuCheckStats(
            enabled=True,
            budget=len(ordered),
            configured_budget=len(ordered),
            checked=len(ordered),
            reachable=len(ordered),
        )
        return results, stats

    # gp._run — единственная точка, где мог бы начаться реальный сетевой прогон.
    monkeypatch.setattr(builder.globalping, "_run", fake_run)
    report = build_subscription(c, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert seen["token"] == "ci-fake-token"  # токен из env дошёл до прогона
    assert seen["count"] == 4  # все кандидаты ушли на RU-проверку
    assert len(verified) == 4  # и дальше — на глубокую проверку
    stats = json.loads(c.paths.stats.read_text())
    assert stats["ru_check"]["enabled"] is True
    assert report.ru_summary.startswith("проверено")


def test_config_ru_keys(tmp_path):
    base = json.loads(Path("config/subscription.json").read_text(encoding="utf-8"))
    raw_path = tmp_path / "subscription.json"
    raw_path.write_text(json.dumps(base))
    loaded = load_config(raw_path)
    assert loaded.ru_check_budget == base["ru_check_budget"]
    assert loaded.ru_check_deadline_seconds == float(base["ru_check_deadline_seconds"])
    assert loaded.ru_check_enabled is None
    # кастомные значения
    base["ru_check_enabled"] = False
    base["ru_check_budget"] = 7
    raw_path.write_text(json.dumps(base))
    loaded2 = load_config(raw_path)
    assert loaded2.ru_check_enabled is False and loaded2.ru_check_budget == 7

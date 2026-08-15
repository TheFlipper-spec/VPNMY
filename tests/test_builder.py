import json
from datetime import UTC, datetime

import pytest

import vpnmy.builder as builder
from vpnmy.builder import BuildError, build_subscription
from vpnmy.config import BuildConfig, Paths
from vpnmy.fetcher import FetchResult
from vpnmy.models import CheckResult, ProbeResult, Source


def cfg(tmp, countries):
    ss = (
        Source("u", "U", "https://x/u", "universal"),
        Source("w", "W", "https://x/w", "whitelist"),
    )
    p = Paths(tmp / "b64", tmp / "raw", tmp / "stats", tmp / "hist", countries)
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


def links():
    us = [
        "123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-12d3-a456-426614174001",
        "123e4567-e89b-12d3-a456-426614174002",
    ]
    return [
        f"vless://{u}@{h}:443?encryption=none&security=tls&type=ws&sni=x.com#Germany"
        for u, h in zip(us, ["1.1.1.1", "8.8.8.8", "9.9.9.9"], strict=True)
    ]


def test_build(tmp_path, countries_file, monkeypatch):
    c = cfg(tmp_path, countries_file)
    ls = links()
    monkeypatch.setattr(builder, "resolve_xray", lambda _: "x")
    monkeypatch.setattr(
        builder,
        "fetch_all",
        lambda sources, t, w: [
            FetchResult(s, "\n".join(ls[:2]) if s.category == "universal" else ls[2], 1)
            for s in sources
        ],
    )
    monkeypatch.setattr(builder, "probe_all", lambda ns, t, w: [ProbeResult(n, 20) for n in ns])
    monkeypatch.setattr(
        builder,
        "verify_all",
        lambda ps, **kw: (
            [
                CheckResult(
                    p.node,
                    20,
                    50,
                    10,
                    "RU" if p.node.category == "whitelist" else "DE",
                    "2026-01-01T00:00:00Z",
                    checks_passed=2,
                )
                for p in ps
            ],
            [],
        ),
    )
    r = build_subscription(c, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert r.published == 3 and json.loads(c.paths.stats.read_text())["check_mode"] == "xray"


def test_fail_safe(tmp_path, countries_file, monkeypatch):
    c = cfg(tmp_path, countries_file)
    c.paths.subscription_base64.write_text("old")
    monkeypatch.setattr(builder, "resolve_xray", lambda _: "x")
    monkeypatch.setattr(
        builder,
        "fetch_all",
        lambda sources, t, w: [FetchResult(s, None, 1, "error") for s in sources],
    )
    with pytest.raises(BuildError):
        build_subscription(c)
    assert c.paths.subscription_base64.read_text() == "old"

"""Регрессионные тесты для улучшенного отбора (задачи 1–4) – исправленная версия."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from vpnmy import asn as asn_mod
from vpnmy.config import load_config
from vpnmy.history import (
    DEFAULT_RECENT_WINDOW,
    empty_history,
    load_history,
    record_failure,
    record_skip,
    record_success,
)
from vpnmy.models import CheckResult, Node, ProbeResult, Source
from vpnmy.parser import parse_link
from vpnmy.selector import (
    _classify_candidate,
    infer_country,
    network_key,
    quality_score,
    sample_candidates,
    select_final,
    shortlist,
)

U_BASE = "123e4567-e89b-12d3-a456-42661417"


def node(i, h, c, name="Germany", source_id="s"):
    # Генерируем валидный UUID: последние 4 hex символа — индекс
    uid = f"{U_BASE}{i:04x}"
    return parse_link(
        f"vless://{uid}@{h}:443?encryption=none&security=tls&type=ws&sni=x.com#{name}",
        Source(source_id, "S", "https://x", c),
    )


def hy_node(i, host, category="universal", source="hy"):
    return parse_link(
        f"hysteria2://pw-{i:04x}@{host}:443/?sni=cdn.example&insecure=1#DE-{i}",
        Source(source, "Hy", "https://x/hy", category),
    )


def make_node_direct(host, port=443, user=None, name="x", source_id="s", category="universal"):
    """Создать Node напрямую без парсера (для тестов IPv6/приватных)."""
    if user is None:
        user = f"{U_BASE}0000"
    return Node(
        scheme="vless",
        host=host,
        port=port,
        original_link=f"vless://{user}@{host}:{port}?encryption=none&security=tls#{name}",
        source_id=source_id,
        source_name="S",
        category=category,
        user=user,
        options={"security": "tls", "type": "ws"},
        original_name=name,
    )


# 1. География не влияет на quality_score
def test_quality_score_no_country_bonus():
    history = {"nodes": {}}
    n_de = node(0, "1.1.1.1", "universal", "Germany")
    n_fi = node(1, "1.1.1.2", "universal", "Finland")
    n_ru = node(2, "1.1.1.3", "universal", "Russia")
    r_de = CheckResult(n_de, 10, 100, 5, "DE", "x")
    r_fi = CheckResult(n_fi, 10, 100, 5, "FI", "x")
    r_ru = CheckResult(n_ru, 10, 100, 5, "RU", "x")
    s_de = quality_score(r_de, history, ("FI", "DE", "RU"))
    s_fi = quality_score(r_fi, history, ("FI", "DE", "RU"))
    s_ru = quality_score(r_ru, history, ("FI", "DE", "RU"))
    assert s_de == s_fi == s_ru
    s_de2 = quality_score(r_de, history, ())
    assert s_de == s_de2


def test_quality_score_ignores_preferred_even_with_different_country():
    history = {"nodes": {"a": {"streak": 5, "successes": 5, "failures": 0, "recent": [1,1,1,1,1]}}}
    n = node(0, "1.1.1.1", "universal")
    r1 = CheckResult(n, 10, 100, 5, "FI", "x")
    r2 = CheckResult(n, 10, 100, 5, "RU", "x")
    assert quality_score(r1, history, ("FI", "RU")) == quality_score(r2, history, ("FI", "RU"))


# 2. Shortlist не продвигает FI
def test_shortlist_does_not_prefer_country():
    history = {"nodes": {}}
    n_fi = node(0, "1.1.1.1", "universal", "🇫🇮 Fast")
    n_de = node(1, "1.1.1.2", "universal", "DE-1")
    assert infer_country(n_fi) == "FI"
    assert infer_country(n_de) == "DE"
    p_fi = ProbeResult(n_fi, 50)
    p_de = ProbeResult(n_de, 50)
    out = shortlist([p_fi, p_de], history, {"universal": 2}, 2, ("FI", "DE"), max_per_subnet=5)
    # Both should be selected
    assert len(out) == 2
    from vpnmy.selector import _rank_key
    rows = {}
    key_pref = _rank_key(rows, ("FI", "DE", "RU"))
    key_empty = _rank_key(rows, ())
    k_fi_pref = key_pref(p_fi)
    k_de_pref = key_pref(p_de)
    k_fi_empty = key_empty(p_fi)
    k_de_empty = key_empty(p_de)
    assert k_fi_pref[0] == k_de_pref[0]
    assert k_fi_pref[1] == k_de_pref[1] == 50
    assert k_fi_pref == k_fi_empty
    assert k_de_pref == k_de_empty


# limits country, ASN, IP, subnet, IPv6, domain
def test_country_limit():
    results = []
    for i in range(5):
        # Use public IPs 8.8.8.x etc but need distinct /24? For country limit not subnet
        ip = f"8.8.8.{10+i}"
        n = node(i, ip, "universal", f"DE-{i}")
        results.append(CheckResult(n, 10, 100+i, 5, "DE", "x", resolved_ip=ip))
    out = select_final(results, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 10}, target_count=5, max_per_endpoint=1, max_per_subnet=10, max_per_country=3)
    assert len(out) == 3
    assert all(r.country == "DE" for r in out)


def test_asn_limit():
    results = []
    for i in range(5):
        ip = f"9.9.9.{10+i}"
        n = node(i, ip, "universal")
        results.append(CheckResult(n, 10, 100+i, 5, "DE", "x", resolved_ip=ip, asn="AS12345"))
    out = select_final(results, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 10}, target_count=5, max_per_endpoint=1, max_per_subnet=10, max_per_asn=2)
    assert len(out) == 2
    # unknown ASN should not be merged
    results2 = [
        CheckResult(node(0, "1.1.1.1", "universal"), 10, 100, 5, "DE", "x", resolved_ip="1.1.1.1", asn=""),
        CheckResult(node(1, "1.1.1.2", "universal"), 10, 101, 5, "DE", "x", resolved_ip="1.1.1.2", asn=""),
        CheckResult(node(2, "1.1.1.3", "universal"), 10, 102, 5, "DE", "x", resolved_ip="1.1.1.3", asn=""),
    ]
    out2 = select_final(results2, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 10}, target_count=5, max_per_endpoint=1, max_per_subnet=10, max_per_asn=2)
    assert len(out2) == 3


def test_ip_limit():
    n1 = parse_link(f"vless://{U_BASE}0000@one.example.com:443?encryption=none&security=tls&type=ws&sni=x.com#x", Source("s", "S", "https://x", "universal"))
    n2 = parse_link(f"vless://{U_BASE}0001@two.example.com:443?encryption=none&security=tls&type=ws&sni=x.com#x", Source("s", "S", "https://x", "universal"))
    r1 = CheckResult(n1, 10, 100, 5, "DE", "x", resolved_ip="5.5.5.5")
    r2 = CheckResult(n2, 10, 101, 5, "DE", "x", resolved_ip="5.5.5.5")
    out = select_final([r1, r2], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=1, max_per_subnet=10, max_per_ip=1)
    assert len(out) == 1
    r3 = CheckResult(node(2, "6.6.6.6", "universal"), 10, 102, 5, "DE", "x", resolved_ip="6.6.6.6")
    out2 = select_final([r1, r3], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=1, max_per_subnet=10, max_per_ip=1)
    assert len(out2) == 2


def test_subnet_limits_ipv4_ipv6():
    # Use public IPs in same /24 for IPv4 limit
    results = []
    base = "185.199.110"  # GitHub public range
    for i in range(3):
        ip = f"{base}.{i+10}"
        n = node(i, ip, "universal")
        results.append(CheckResult(n, 10, 100+i, 5, "DE", "x", resolved_ip=ip))
    out = select_final(results, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 5}, target_count=5, max_per_endpoint=1, max_per_subnet=2)
    assert len(out) == 2
    # IPv6 same /48 should be limited using direct Nodes with global IPv6
    # Use global IPv6 addresses (2001:67c:750:: etc is global, but use 2a01)
    results_v6 = []
    ips_v6 = ["2a01:4f8:c010:1::1", "2a01:4f8:c010:1::2", "2a01:4f8:c010:1::3"]
    for i, ip in enumerate(ips_v6):
        n = make_node_direct(ip)
        results_v6.append(CheckResult(n, 10, 100+i, 5, "DE", "x", resolved_ip=ip))
    out6 = select_final(results_v6, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 5}, target_count=5, max_per_endpoint=1, max_per_subnet=2)
    assert len(out6) == 2
    # Different /48 should both pass with max_per_subnet=1 (third hextet differs)
    ip1 = "2a01:4f8:c010:1::1"
    ip2 = "2a01:4f8:c011:1::1"
    r1 = CheckResult(make_node_direct(ip1), 10, 100, 5, "DE", "x", resolved_ip=ip1)
    r2 = CheckResult(make_node_direct(ip2), 10, 101, 5, "DE", "x", resolved_ip=ip2)
    out_diff = select_final([r1, r2], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=10, max_per_subnet=1)
    assert len(out_diff) == 2
    # Verify network_key documented sizes
    assert network_key("8.8.8.1:443").endswith("/24")
    k1 = network_key("2a01:4f8:c010:1::1:443")
    k2 = network_key("2a01:4f8:c010:1::2:443")
    assert k1 == k2  # same /48 (first 48 bits = 2a01:4f8:c010)
    k3 = network_key("2a01:4f8:c011:1::1:443")
    assert k1 != k3


def test_domain_endpoint_uses_resolved_ip():
    n1 = parse_link(f"vless://{U_BASE}0000@a.example.com:443?encryption=none&security=tls#x", Source("s", "S", "https://x", "universal"))
    n2 = parse_link(f"vless://{U_BASE}0001@b.example.com:443?encryption=none&security=tls#x", Source("s", "S", "https://x", "universal"))
    pr1 = ProbeResult(n1, 10, resolved_ip="9.9.9.9")
    pr2 = ProbeResult(n2, 12, resolved_ip="9.9.9.9")
    assert network_key(pr1.endpoint_key) == network_key(pr2.endpoint_key)
    assert pr1.endpoint_key == "9.9.9.9:443"
    r1 = CheckResult(n1, 10, 100, 5, "DE", "x", resolved_ip="9.9.9.9")
    r2 = CheckResult(n2, 10, 101, 5, "DE", "x", resolved_ip="9.9.9.9")
    out = select_final([r1, r2], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=10, max_per_subnet=10, max_per_ip=1)
    assert len(out) == 1


def test_egress_ip_dedup():
    n1 = node(0, "1.1.1.1", "universal")
    n2 = node(1, "2.2.2.2", "universal")
    r1 = CheckResult(n1, 10, 100, 5, "DE", "x", resolved_ip="1.1.1.1", egress_ip="8.8.8.8")
    r2 = CheckResult(n2, 10, 101, 5, "DE", "x", resolved_ip="2.2.2.2", egress_ip="8.8.8.8")
    out = select_final([r1, r2], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=10, max_per_subnet=10)
    assert len(out) == 1
    r3 = CheckResult(n2, 10, 101, 5, "DE", "x", resolved_ip="2.2.2.2", egress_ip="9.9.9.9")
    out2 = select_final([r1, r3], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=10, max_per_subnet=10)
    assert len(out2) == 2


def test_unknown_asn_and_service_unavailable():
    with patch("vpnmy.asn.enrich_asns", side_effect=Exception("network down")):
        results = [CheckResult(node(i, f"9.9.9.{10+i}", "universal"), 10, 100, 5, "DE", "x", resolved_ip=f"9.9.9.{10+i}") for i in range(3)]
        out = select_final(results, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 3}, target_count=3, max_per_endpoint=10, max_per_subnet=10, max_per_country=10, max_per_asn=2)
        assert len(out) == 3
    with patch("requests.Session.get", side_effect=Exception("timeout")):
        ip_map = {"1.1.1.1": "", "2.2.2.2": ""}
        enriched = asn_mod.enrich_asns(ip_map)
        assert enriched["1.1.1.1"] == ""
        assert enriched["2.2.2.2"] == ""
    results_unknown = [CheckResult(node(i, f"1.1.1.{i+1}", "universal"), 10, 100+i, 5, "DE", "x", resolved_ip=f"1.1.1.{i+1}", asn="") for i in range(4)]
    out_unknown = select_final(results_unknown, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 4}, target_count=4, max_per_asn=2, max_per_country=10, max_per_subnet=10, max_per_ip=10)
    assert len(out_unknown) == 4


def test_median_spread_and_threshold():
    history = {"nodes": {}}
    n_unstable = node(0, "1.1.1.1", "universal")
    n_stable = node(1, "2.2.2.2", "universal")
    r_unstable = CheckResult(n_unstable, 10, 450, 5, "DE", "x", http_max_ms=3800, jitter_ms=3400, samples=(400,450,3800), attempts=3)
    r_stable = CheckResult(n_stable, 10, 680, 5, "DE", "x", http_max_ms=700, jitter_ms=50, samples=(650,700,680), attempts=3)
    score_unstable = quality_score(r_unstable, history, ())
    score_stable = quality_score(r_stable, history, ())
    assert score_stable > score_unstable
    out = select_final([r_unstable, r_stable], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 1}, target_count=1, max_per_endpoint=10, max_per_subnet=10)
    assert out[0].node.node_id == r_stable.node.node_id

    r_slow = CheckResult(node(2, "3.3.3.3", "universal"), 10, 1600, 5, "DE", "x")
    r_fast = CheckResult(node(3, "4.4.4.4", "universal"), 10, 1400, 5, "DE", "x")
    out_thr = select_final([r_slow, r_fast], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 2}, target_count=2, max_per_endpoint=10, max_per_subnet=10, verify_median_threshold_ms=1500)
    assert len(out_thr) == 1 and out_thr[0].node.node_id == r_fast.node.node_id
    out_all_slow = select_final([r_slow], history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 1}, target_count=1, max_per_endpoint=10, verify_median_threshold_ms=1500)
    assert out_all_slow == []

    r_timeout = CheckResult(node(4, "5.5.5.5", "universal"), 10, 450, 5, "DE", "x", http_max_ms=8000, jitter_ms=7600, samples=(400,450,8000), attempts=3)
    score_timeout = quality_score(r_timeout, history, ())
    assert score_timeout < score_stable


def test_sliding_window_and_migration(tmp_path):
    old_history = {
        "schema_version": 1,
        "nodes": {
            "abc": {"successes": 5, "failures": 1, "streak": 3, "last_seen": "2026-09-14T00:00:00Z", "country": "DE"},
            "def": {"successes": 0, "failures": 5, "streak": 0, "last_seen": "2026-09-10T00:00:00Z"},
        }
    }
    p = tmp_path / "hist.json"
    p.write_text(json.dumps(old_history))
    loaded = load_history(p)
    assert "recent" in loaded["nodes"]["abc"]
    assert loaded["nodes"]["abc"]["successes"] == 5
    assert len(loaded["nodes"]["abc"]["recent"]) == 3
    assert loaded["nodes"]["def"]["recent"] == []

    n = node(0, "1.1.1.1", "universal")
    node_id = n.node_id
    history_match = {"nodes": {node_id: {"successes": 100, "failures": 1, "streak": 0, "recent": [0,0,0,0,0]}}}
    r = CheckResult(n, 10, 100, 5, "DE", "x")
    score_low = quality_score(r, history_match, ())
    history_high = {"nodes": {node_id: {"successes": 100, "failures": 1, "streak": 5, "recent": [1,1,1,1,1]}}}
    score_high = quality_score(r, history_high, ())
    assert score_high > score_low

    hist = empty_history()
    n = node(99, "9.9.9.9", "universal")
    for i in range(25):
        cr = CheckResult(n, 10, 100+i%10, 5, "DE", f"2026-09-15T00:00:{i:02d}Z")
        record_success(hist, cr)
    row = hist["nodes"][n.node_id]
    assert len(row["recent"]) <= DEFAULT_RECENT_WINDOW
    assert len(row["latency_medians"]) <= 20


def test_skipped_not_counted_as_failure(tmp_path):
    hist = empty_history()
    n = node(0, "1.1.1.1", "universal")
    r = CheckResult(n, 10, 100, 5, "DE", "2026-09-15T00:00:00Z")
    record_success(hist, r)
    row_before = dict(hist["nodes"][n.node_id])
    record_skip(hist, n, "2026-09-15T01:00:00Z")
    row_after = hist["nodes"][n.node_id]
    assert row_after["successes"] == row_before["successes"]
    assert row_after["failures"] == row_before["failures"]
    assert row_after["streak"] == row_before["streak"]
    assert row_after["recent"] == row_before["recent"]
    record_failure(hist, n, "2026-09-15T02:00:00Z")
    assert hist["nodes"][n.node_id]["failures"] == row_before["failures"] + 1
    assert hist["nodes"][n.node_id]["streak"] == 0
    assert hist["nodes"][n.node_id]["recent"][-1] == 0


def test_70_30_budgets_and_redistribution():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    history = {"nodes": {}}
    known_nodes = []
    for i in range(10):
        n = node(i, f"8.8.8.{10+i}", "universal", source_id=f"src{i%2}")
        history["nodes"][n.node_id] = {"streak": 5, "successes": 5, "failures": 0, "last_seen": now.isoformat().replace("+00:00", "Z"), "recent": [1,1,1]}
        known_nodes.append(n)
    new_nodes = [node(100+i, f"1.1.1.{10+i}", "universal") for i in range(10)]
    all_nodes = known_nodes + new_nodes
    selected = sample_candidates(all_nodes, history, limit=10, now=now)
    known_selected = sum(1 for n in selected if n.node_id in {k.node_id for k in known_nodes})
    explore_selected = len(selected) - known_selected
    assert known_selected == 7 and explore_selected == 3

    small_known = known_nodes[:2]
    all_small = small_known + new_nodes
    selected2 = sample_candidates(all_small, history, limit=10, now=now)
    known2 = sum(1 for n in selected2 if n.node_id in {k.node_id for k in small_known})
    assert known2 == 2
    assert len(selected2) == 10
    assert len(selected2) - known2 == 8

    few_new = new_nodes[:1]
    all_many_known = known_nodes + few_new
    selected3 = sample_candidates(all_many_known, history, limit=10, now=now)
    new_sel = sum(1 for n in selected3 if n.node_id in {x.node_id for x in few_new})
    assert new_sel == 1
    assert len(selected3) == 10
    assert len(selected3) - new_sel == 9


def test_rotation_deterministic():
    now1 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    now2 = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
    history = {"nodes": {}}
    nodes = [node(i, f"9.9.9.{10+i}", "universal") for i in range(20)]
    sel1 = sample_candidates(nodes, history, limit=6, now=now1)
    sel2 = sample_candidates(nodes, history, limit=6, now=now2)
    assert sel1 != sel2
    sel1_again = sample_candidates(nodes, history, limit=6, now=now1)
    assert sel1 == sel1_again


def test_no_starvation_over_slots():
    now_base = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    history = {"nodes": {}}
    nodes = [node(i, f"8.8.4.{10+i}", "universal") for i in range(20)]
    seen = set()
    for hour in range(20):
        now = now_base + timedelta(hours=hour)
        sel = sample_candidates(nodes, history, limit=5, now=now)
        for n in sel:
            seen.add(n.node_id)
    assert len(seen) == 20


def test_hysteria_retains_share():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    history = {"nodes": {}}
    classic = [node(i, f"185.199.110.{10+i}", "universal") for i in range(20)]
    for n in classic[:5]:
        history["nodes"][n.node_id] = {"streak": 2, "successes": 2, "failures": 0, "last_seen": now.isoformat().replace("+00:00","Z"), "recent":[1,1]}
    hy = [hy_node(i, f"185.199.111.{10+i}") for i in range(3)]
    for n in hy:
        history["nodes"][n.node_id] = {"streak": 2, "successes": 2, "failures": 0, "last_seen": now.isoformat().replace("+00:00","Z"), "recent":[1,1]}
    all_nodes = classic + hy
    selected = sample_candidates(all_nodes, history, limit=10, now=now)
    assert any(n.is_hysteria for n in selected)
    assert any(not n.is_hysteria for n in selected)
    probes = [ProbeResult(n, 50) for n in classic[:10]] + [ProbeResult(n, 50) for n in hy]
    out = shortlist(probes, history, {"universal": 4}, 4, (), max_per_subnet=10)
    assert any(p.node.is_hysteria for p in out)
    assert any(not p.node.is_hysteria for p in out)


def test_lack_of_good_nodes_no_silent_weakening():
    results = [
        CheckResult(node(0, "1.1.1.1", "universal"), 10, 100, 5, "DE", "x", resolved_ip="1.1.1.1"),
        CheckResult(node(1, "2.2.2.2", "universal"), 10, 101, 5, "DE", "x", resolved_ip="2.2.2.2"),
    ]
    out = select_final(results, history={"nodes": {}}, preferred_countries=(), category_quotas={"universal": 5}, target_count=5, max_per_endpoint=1, max_per_subnet=10)
    assert len(out) == 2


def test_old_configs_remain_readable(tmp_path):
    old = {
        "schema_version": 1,
        "sources": [{"id": "x", "name": "X", "url": "https://example.com/s", "category": "universal"}],
        "paths": {"subscription_base64": "a", "subscription_raw": "b", "stats": "c", "history": "d", "countries": "e"},
        "target_count": 3,
        "min_publish_count": 1,
        "max_candidates": 10,
        "max_per_endpoint": 1,
        "category_quotas": {"universal": 3},
        "preferred_countries": ["FI", "DE"],
        "fetch_workers": 1,
        "probe_workers": 1,
        "verify_workers": 1,
        "source_timeout_seconds": 5,
        "tcp_timeout_seconds": 1,
        "verify_timeout_seconds": 5,
        "speed_test_bytes": 0,
        "xray_bin": "xray"
    }
    p = tmp_path / "config"
    p.mkdir()
    f = p / "subscription.json"
    f.write_text(json.dumps(old))
    cfg = load_config(f)
    assert cfg.max_per_country == 3
    assert cfg.max_per_asn == 2
    assert cfg.verify_measurements == 3
    assert cfg.preferred_countries == ("FI", "DE")


def test_classification_new_known_stale():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    n_new = node(0, "1.1.1.1", "universal")
    assert _classify_candidate(n_new, {"nodes": {}}, now) == "new"
    hist_known = {"nodes": {n_new.node_id: {"streak": 2, "successes": 2, "last_seen": now.isoformat().replace("+00:00","Z"), "recent": [1,1]}}}
    assert _classify_candidate(n_new, hist_known, now) == "known"
    old_time = (now - timedelta(days=5)).isoformat().replace("+00:00","Z")
    hist_stale = {"nodes": {n_new.node_id: {"streak": 0, "successes": 1, "failures": 5, "last_seen": old_time, "recent": [0,0]}}}
    assert _classify_candidate(n_new, hist_stale, now) == "stale"


def test_ipv6_and_domain_handling():
    ip6_1 = "2a01:4f8:c010:1::1"
    ip6_2 = "2a01:4f8:c010:1::2"
    assert network_key(f"{ip6_1}:443") == network_key(f"{ip6_2}:443")
    ip6_3 = "2a01:4f8:c011:1::1"
    assert network_key(f"{ip6_1}:443") != network_key(f"{ip6_3}:443")
    with patch("vpnmy.asn.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"status": "ok", "data": {"asn": 12345}}
        mock_get.return_value = mock_resp
        asn_mod.enrich_asns({"1.1.1.1": ""})
        called_url = mock_get.call_args[0][0] if mock_get.call_args else ""
        assert "1.1.1.1" in called_url
        assert "vless" not in called_url.lower()

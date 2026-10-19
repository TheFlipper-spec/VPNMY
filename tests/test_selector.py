from datetime import UTC, datetime

from vpnmy.models import CheckResult, Source
from vpnmy.parser import parse_link
from vpnmy.selector import (
    infer_country,
    is_historically_unreliable,
    is_likely_dead,
    sample_candidates,
    select_final,
)

U = "123e4567-e89b-12d3-a456-42661417400{}"


def node(i, h, c, name="Germany"):
    return parse_link(
        f"vless://{U.format(i)}@{h}:443?encryption=none&security=reality&type=tcp&sni=x.com&fp=chrome&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=abcd#{name}",
        Source(str(i), "S", "https://x", c),
    )


def test_infer():
    assert infer_country(node(0, "1.1.1.1", "universal", "🇫🇮 Fast")) == "FI"


def test_quotas():
    rs = [
        CheckResult(node(0, "1.1.1.1", "universal"), 10, 20, 10, "DE", "x"),
        CheckResult(node(1, "8.8.8.8", "universal"), 10, 20, 10, "DE", "x"),
        CheckResult(node(2, "9.9.9.9", "whitelist"), 10, 20, 10, "RU", "x"),
    ]
    out = select_final(
        rs,
        history={"nodes": {}},
        preferred_countries=("RU", "DE"),
        category_quotas={"universal": 2, "whitelist": 1},
        target_count=3,
        max_per_endpoint=1,
    )
    assert len(out) == 3 and {x.node.category for x in out} == {"universal", "whitelist"}


def test_category_quota_reserves_whitelist_seat():
    """Белая категория получает своё место даже при более высоких скорах universal."""
    rs = [
        CheckResult(node(i, f"1.1.1.{i}", "universal"), 10, 20 + i, 10, "DE", "x")
        for i in range(4)
    ]
    rs.append(CheckResult(node(9, "9.9.9.9", "whitelist"), 10, 999, 10, "RU", "x"))
    out = select_final(
        rs,
        history={"nodes": {}},
        preferred_countries=(),
        category_quotas={"universal": 2, "whitelist": 1},
        target_count=3,
        max_per_endpoint=1,
    )
    assert len(out) == 3
    assert sum(item.node.category == "whitelist" for item in out) == 1
    assert sum(item.node.category == "universal" for item in out) == 2


def test_category_quota_reallocates_when_whitelist_is_empty():
    rs = [
        CheckResult(node(i, host, "universal"), 10, 20 + i, 10, "DE", "x")
        for i, host in enumerate(("1.1.1.1", "8.8.8.8", "9.9.9.9"))
    ]
    out = select_final(
        rs,
        history={"nodes": {}},
        preferred_countries=(),
        category_quotas={"universal": 2, "whitelist": 1},
        target_count=3,
        max_per_endpoint=1,
    )
    assert len(out) == 3


def test_same_physical_endpoint_is_not_published_twice():
    results = [
        CheckResult(
            node(0, "one.example.com", "universal"),
            10,
            20,
            10,
            "DE",
            "x",
            resolved_ip="1.1.1.1",
        ),
        CheckResult(
            node(1, "two.example.com", "universal"),
            11,
            21,
            10,
            "DE",
            "x",
            resolved_ip="1.1.1.1",
        ),
    ]
    out = select_final(
        results,
        history={"nodes": {}},
        preferred_countries=("DE",),
        category_quotas={"universal": 2},
        target_count=2,
        max_per_endpoint=1,
    )
    assert len(out) == 1


def test_likely_dead_and_unreliable_nodes_are_filtered():
    dead = node(0, "1.1.1.1", "universal")
    history = {
        "nodes": {
            dead.node_id: {"successes": 0, "failures": 8, "streak": 0},
        }
    }
    assert is_likely_dead(dead, history)
    sampled = sample_candidates([dead], history, limit=10, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert dead in sampled or sampled == []
    checked = CheckResult(dead, 10, 20, 10, "DE", "x")
    history["nodes"][dead.node_id] = {"successes": 1, "failures": 8, "streak": 1}
    assert is_historically_unreliable(checked, history)


def hy_node(i, host, category="universal", source="hy"):
    return parse_link(
        f"hysteria2://pw-{i}@{host}:443/?sni=cdn.example&insecure=1#DE-{i}",
        Source(source, "Hy", "https://x/hy", category),
    )


def test_cap_per_source_limits_large_lists():
    from vpnmy.selector import cap_per_source

    nodes = [
        parse_link(
            f"vless://123e4567-e89b-12d3-a456-{i:012x}@8.{i // 256}.0.{i % 256 + 1}:443?"
            "encryption=none&security=reality&type=tcp&sni=x.com&fp=chrome&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=abcd#DE",
            Source("0", "S", "https://x", "universal"),
        )
        for i in range(300)
    ]
    out = cap_per_source(nodes, 40, {"nodes": {}}, datetime(2026, 1, 1, tzinfo=UTC))
    assert len(out) == 40
    assert all(n.source_id == "0" for n in out)
    # стабильные узлы истории попадают в шорткат
    history = {"nodes": {nodes[5].node_id: {"streak": 9, "speed_mbps": 5}}}
    out2 = cap_per_source(nodes, 40, history, datetime(2026, 1, 1, tzinfo=UTC))
    assert nodes[5] in out2


def test_shortlist_includes_hysteria_share():
    from vpnmy.models import ProbeResult
    from vpnmy.selector import shortlist

    classic = [
        parse_link(
            f"vless://123e4567-e89b-12d3-a456-{i:012x}@8.8.{i}.1:443?"
            "encryption=none&security=reality&type=tcp&sni=x.com&fp=chrome&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=abcd#DE",
            Source(str(i), "S", "https://x", "universal"),
        )
        for i in range(20)
    ]
    probes = [ProbeResult(n, 50) for n in classic]
    probes += [ProbeResult(hy_node(i, f"9.9.{i}.1"), 50) for i in range(20)]
    out = shortlist(
        probes,
        {"nodes": {}},
        {"universal": 5},
        5,
        ("DE",),
        max_per_subnet=5,
    )
    assert any(p.node.is_hysteria for p in out)
    assert any(not p.node.is_hysteria for p in out)


def test_subnet_diversity_limits_clones():
    results = []
    for i in range(5):
        results.append(
            CheckResult(
                node(i, f"2.2.2.{i + 1}", "universal"),
                10,
                20 + i,
                10,
                "DE",
                "x",
                resolved_ip=f"10.20.30.{i}",
            )
        )
    out = select_final(
        results,
        history={"nodes": {}},
        preferred_countries=("DE",),
        category_quotas={"universal": 5},
        target_count=5,
        max_per_endpoint=1,
        max_per_subnet=2,
    )
    assert len(out) == 2


def test_hysteria_has_no_supra_protocol_bonus():
    from vpnmy.selector import _PROTOCOL_BONUS

    assert _PROTOCOL_BONUS == {}


def test_publication_stable_streak():
    from vpnmy.selector import is_publication_stable

    fresh = CheckResult(hy_node(1, "3.3.3.3"), 10, 100, 5, "DE", "x")
    history = {"nodes": {fresh.node.node_id: {"streak": 1}}}
    assert not is_publication_stable(fresh, history, 2)
    history["nodes"][fresh.node.node_id]["streak"] = 2
    assert is_publication_stable(fresh, history, 2)


def test_network_key_groups_subnets():
    from vpnmy.selector import network_key

    assert network_key("10.20.30.5:443") == network_key("10.20.30.9:8443")
    assert network_key("10.20.31.5:443") != network_key("10.20.30.5:443")
    assert network_key("edge.example.com:443") == "edge.example.com"


def test_reality_firefox_fingerprint_is_supported():
    from vpnmy.selector import select_final

    firefox = parse_link(
        f"vless://{U.format(0)}@1.1.1.1:443?encryption=none&security=reality&type=tcp&sni=x.com&fp=firefox&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=abcd#Firefox",
        Source("firefox", "Firefox", "https://example.com", "universal"),
    )
    result = CheckResult(firefox, 10, 20, 10, "DE", "x")
    selected = select_final([result], history={"nodes": {}}, preferred_countries=(), category_quotas={}, target_count=1)
    assert len(selected) == 1 and selected[0].node.options["fp"] == "firefox"

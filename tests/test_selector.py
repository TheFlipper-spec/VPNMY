from vpnmy.models import CheckResult, Source
from vpnmy.parser import parse_link
from vpnmy.selector import infer_country, select_final

U = "123e4567-e89b-12d3-a456-42661417400{}"


def node(i, h, c, name="Germany"):
    return parse_link(
        f"vless://{U.format(i)}@{h}:443?encryption=none&security=tls&type=ws&sni=x.com#{name}",
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

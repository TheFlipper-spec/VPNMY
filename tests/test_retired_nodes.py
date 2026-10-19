from datetime import UTC, datetime

from vpnmy.history import empty_history, record_failure
from vpnmy.models import Node
from vpnmy.selector import is_likely_dead, sample_candidates


def test_repeatedly_failed_node_is_retired_and_not_selected():
    node = Node(
        scheme="vless",
        host="203.0.113.10",
        port=443,
        original_link="vless://dead",
        source_id="test",
        source_name="test",
        category="universal",
        user="uuid",
    )
    history = empty_history()
    for index in range(4):
        record_failure(history, node, f"2026-01-0{index + 1}T00:00:00Z")
    assert history["nodes"][node.node_id]["retired"] is True
    assert is_likely_dead(node, history)
    assert sample_candidates([node], history, limit=10, now=datetime(2026, 1, 10, tzinfo=UTC)) == []

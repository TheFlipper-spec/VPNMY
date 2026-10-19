import io

from vpnmy import rkn_filter


def test_lists_are_cached_and_checked(monkeypatch):
    calls = []
    payloads = {
        rkn_filter.IP_LIST_URL: b"203.0.113.0/24\n",
        rkn_filter.DOMAIN_LIST_URL: b"blocked.example\n",
    }

    def open_url(url, timeout):
        calls.append(url)
        return io.BytesIO(payloads[url])

    monkeypatch.setattr(rkn_filter, "urlopen", open_url)
    rkn_filter.reset_cache()
    assert rkn_filter.is_ip_blocked("203.0.113.8")
    assert rkn_filter.is_sni_blocked("sub.blocked.example")
    assert not rkn_filter.is_sni_blocked("example.com")
    assert len(calls) == 2
    rkn_filter.reset_cache()

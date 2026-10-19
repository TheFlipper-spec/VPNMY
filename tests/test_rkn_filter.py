import io
import ipaddress

import pytest

from vpnmy import rkn_filter


@pytest.fixture(autouse=True)
def isolated_cache():
    rkn_filter.reset_cache()
    yield
    rkn_filter.reset_cache()


def install_lists(monkeypatch, ips="", domains=""):
    calls = []
    payloads = {
        rkn_filter.IP_LIST_URL: ips.encode(),
        rkn_filter.DOMAIN_LIST_URL: domains.encode(),
    }

    def open_url(url, timeout):
        calls.append(url)
        return io.BytesIO(payloads[url])

    monkeypatch.setattr(rkn_filter, "urlopen", open_url)
    return calls, payloads


def test_lists_are_cached_and_checked(monkeypatch):
    calls, _payloads = install_lists(monkeypatch, "203.0.113.0/24\n", "blocked.example\n")
    assert rkn_filter.is_ip_blocked("203.0.113.8")
    assert rkn_filter.is_sni_blocked("sub.blocked.example")
    assert not rkn_filter.is_sni_blocked("example.com")
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("203.0.112.255", False),
        ("203.0.113.0", True),
        ("203.0.113.127", True),
        ("203.0.113.255", True),
        ("203.0.114.0", False),
        ("192.0.2.127", False),
        ("192.0.2.128", True),
        ("192.0.2.191", True),
        ("192.0.2.192", False),
        ("198.51.100.3", False),
        ("198.51.100.4", True),
        ("198.51.100.5", False),
        ("2001:db8::", True),
        ("2001:db8::3", True),
        ("2001:db8::4", False),
        ("2001:db8:1::f", True),
        ("2001:db8:1::e", False),
        ("0.0.0.0", False),
        ("255.255.255.255", True),
        ("::", False),
        ("ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", True),
        ("example.com", False),
        ("not an IP", False),
    ],
)
def test_indexed_ip_boundaries_overlap_and_address_families(monkeypatch, address, expected):
    # Unsorted, overlapping, adjacent and duplicate ranges; host bits are normalized.
    install_lists(
        monkeypatch,
        "2001:db8:1::f/128\n203.0.113.128/25\n203.0.113.0/26\n"
        "203.0.113.32/27\n203.0.113.64/26\n203.0.113.128/25\n"
        "192.0.2.190/26\n198.51.100.4\n2001:db8::/126\n2001:db8::2/128\n"
        "255.255.255.255\nffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff\ninvalid\n# comment\n",
    )
    assert rkn_filter.is_ip_blocked(address) is expected


@pytest.mark.parametrize(
    ("sni", "expected"),
    [
        ("blocked.example", True),
        ("deep.sub.blocked.example", True),
        ("  SUB.Blocked.Example.  ", True),
        ("notblocked.example", False),
        ("blocked.example.evil", False),
        ("example", False),
        ("", False),
    ],
)
def test_domain_suffix_boundaries_and_normalization(monkeypatch, sni, expected):
    install_lists(monkeypatch, domains=".Blocked.Example. # comment\n\n# ignored\n")
    assert rkn_filter.is_sni_blocked(sni) is expected


def test_force_refresh_replaces_both_indexes(monkeypatch):
    calls, payloads = install_lists(monkeypatch, "203.0.113.0/24\n", "old.example\n")
    rkn_filter.load_lists()
    payloads[rkn_filter.IP_LIST_URL] = b"2001:db8::/32\n"
    payloads[rkn_filter.DOMAIN_LIST_URL] = b"new.example\n"
    rkn_filter.load_lists()
    assert len(calls) == 2
    assert rkn_filter.is_sni_blocked("old.example")
    rkn_filter.load_lists(force=True)
    assert len(calls) == 4
    assert not rkn_filter.is_ip_blocked("203.0.113.8")
    assert rkn_filter.is_ip_blocked("2001:db8::1")
    assert not rkn_filter.is_sni_blocked("old.example")
    assert rkn_filter.is_sni_blocked("new.example")


def test_failed_downloads_fail_open_and_are_cached(monkeypatch):
    calls = []

    def unavailable(url, timeout):
        calls.append(url)
        raise OSError("offline")

    monkeypatch.setattr(rkn_filter, "urlopen", unavailable)
    for _ in range(3):
        assert not rkn_filter.is_ip_blocked("203.0.113.8")
        assert not rkn_filter.is_ip_blocked("2001:db8::1")
        assert not rkn_filter.is_sni_blocked("example.com")
    assert len(calls) == 2


def test_ip_lookup_is_logarithmic_without_timing_assertions(monkeypatch):
    class IndexedStarts:
        """65K disjoint intervals; prohibit iteration and count indexed reads."""

        reads = 0

        def __len__(self):
            return 65_536

        def __getitem__(self, index):
            self.reads += 1
            return index * 4

        def __iter__(self):
            raise AssertionError("IP lookup must not scan the list")

    starts = IndexedStarts()
    monkeypatch.setattr(rkn_filter, "load_lists", lambda: None)
    monkeypatch.setattr(rkn_filter, "_ip_ranges", {4: (starts, range(1, len(starts) * 4, 4))})
    for offset, expected in ((0, True), (1, True), (2, False)):
        starts.reads = 0
        address = str(ipaddress.IPv4Address((len(starts) - 1) * 4 + offset))
        assert rkn_filter.is_ip_blocked(address) is expected
        assert starts.reads <= 17


def test_sni_lookup_does_not_scan_large_domain_list(monkeypatch):
    class LookupOnlyDomains(frozenset):
        lookups = 0

        def __contains__(self, item):
            self.lookups += 1
            return super().__contains__(item)

        def __iter__(self):
            raise AssertionError("SNI lookup must not scan the list")

    domains = LookupOnlyDomains(["blocked.example", *(f"{i}.other.example" for i in range(65_536))])
    monkeypatch.setattr(rkn_filter, "load_lists", lambda: None)
    monkeypatch.setattr(rkn_filter, "_domains", domains)
    assert rkn_filter.is_sni_blocked("deep.sub.blocked.example")
    assert domains.lookups == 3
    domains.lookups = 0
    assert not rkn_filter.is_sni_blocked("unlisted.example")
    assert domains.lookups == 2

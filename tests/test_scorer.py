"""Scorer pure-function tests."""

from dataclasses import replace

from mirror_bench.benchmark.scorer import (
    drop_stale,
    filter_for_policy,
    prefer_https,
    score_results,
    sync_ages,
)
from mirror_bench.models import Mirror, ProbeResult, Weights


def make_probe(
    url: str = "https://a.example.org/ubuntu/",
    ttfb_ms: float | None = 50.0,
    bps: float | None = 1_000_000.0,
    tls: str | None = "TLSv1.3",
    http: str | None = "HTTP/2",
    cert_valid: bool | None = True,
    status: int | None = 200,
    error: str | None = None,
) -> ProbeResult:
    m = Mirror(
        url=url,
        host=url.split("//")[1].split("/")[0],
        country=None,
        protocols=("https",) if url.startswith("https") else ("http",),
    )
    return ProbeResult(
        mirror=m,
        ttfb_ms=ttfb_ms,
        total_ms=ttfb_ms,
        bytes_read=1024,
        bytes_per_sec=bps,
        status=status,
        http_version=http,
        tls_version=tls,
        cert_valid=cert_valid,
        error=error,
    )


def test_empty_results_returns_empty() -> None:
    assert score_results([], None, Weights()) == []


def test_failed_probes_excluded() -> None:
    good = make_probe(url="https://good.example.org/u/")
    bad = make_probe(
        url="https://bad.example.org/u/", status=None, error="ConnectError"
    )
    scores = score_results([good, bad], None, Weights())
    assert len(scores) == 1
    assert scores[0].mirror.host == "good.example.org"


def test_weights_shift_ranking() -> None:
    fast_plain_http = make_probe(
        url="http://fast.example.org/u/",
        ttfb_ms=10.0,
        bps=2_000_000.0,
        tls=None,
        http="HTTP/1.1",
        cert_valid=None,
    )
    slow_secure_https = make_probe(
        url="https://secure.example.org/u/",
        ttfb_ms=100.0,
        bps=500_000.0,
    )

    # Latency-heavy weights -> fast_plain_http wins.
    scores = score_results(
        [fast_plain_http, slow_secure_https],
        None,
        Weights(latency=1.0, throughput=0.0, security=0.0),
    )
    assert scores[0].mirror.host == "fast.example.org"

    # Security-heavy weights -> slow_secure_https wins.
    scores = score_results(
        [fast_plain_http, slow_secure_https],
        None,
        Weights(latency=0.0, throughput=0.0, security=1.0),
    )
    assert scores[0].mirror.host == "secure.example.org"


def test_throughput_overrides_latency_phase_bps() -> None:
    a = make_probe(url="https://a.example.org/u/", ttfb_ms=50.0, bps=100.0)
    b = make_probe(url="https://b.example.org/u/", ttfb_ms=50.0, bps=100.0)
    tput_map = {
        a.mirror.url: make_probe(url=a.mirror.url, bps=10_000_000.0),
        b.mirror.url: make_probe(url=b.mirror.url, bps=1_000.0),
    }
    scores = score_results(
        [a, b],
        tput_map,
        Weights(latency=0.0, throughput=1.0, security=0.0),
    )
    assert scores[0].mirror.host == "a.example.org"
    assert scores[0].throughput_bps == 10_000_000.0


def test_normalize_degenerate_set_all_equal() -> None:
    a = make_probe(url="https://a.example.org/u/", ttfb_ms=50.0, bps=1_000.0)
    b = make_probe(url="https://b.example.org/u/", ttfb_ms=50.0, bps=1_000.0)
    scores = score_results([a, b], None, Weights())
    # Tied latency + throughput; composite scores equal.
    assert scores[0].composite == scores[1].composite


def test_filter_https_only() -> None:
    http = make_probe(url="http://plain.example.org/u/")
    https = make_probe(url="https://secure.example.org/u/")
    filtered = filter_for_policy([http, https], https_only=True, tls13_only=False)
    assert len(filtered) == 1
    assert filtered[0].mirror.is_https


def test_filter_tls13_only() -> None:
    tls12 = make_probe(url="https://a.example.org/u/", tls="TLSv1.2")
    tls13 = make_probe(url="https://b.example.org/u/", tls="TLSv1.3")
    filtered = filter_for_policy([tls12, tls13], https_only=False, tls13_only=True)
    assert len(filtered) == 1
    assert filtered[0].tls_version == "TLSv1.3"


def test_security_score_values() -> None:
    # All security features → 2.5
    full = make_probe(
        url="https://x.example.org/u/", tls="TLSv1.3", http="HTTP/2", cert_valid=True
    )
    scores = score_results([full], None, Weights(latency=0, throughput=0, security=1.0))
    assert scores[0].security_score == 2.5
    assert scores[0].composite == 1.0

    # http only → 0
    plain = make_probe(
        url="http://x.example.org/u/", tls=None, http="HTTP/1.1", cert_valid=None
    )
    scores = score_results(
        [plain], None, Weights(latency=0, throughput=0, security=1.0)
    )
    assert scores[0].security_score == 0.0


def test_throughput_https_downgrade_excludes_mirror() -> None:
    good = make_probe(url="https://good.example.org/u/")
    bad = make_probe(url="https://bad.example.org/u/")
    tput_map = {
        good.mirror.url: make_probe(url=good.mirror.url, bps=5_000_000.0),
        bad.mirror.url: make_probe(
            url=bad.mirror.url, bps=None, status=200, error="https_downgrade"
        ),
    }
    scores = score_results([good, bad], tput_map, Weights())
    assert [s.mirror.host for s in scores] == ["good.example.org"]


def test_latency_phase_rate_is_not_reported_as_throughput() -> None:
    a = make_probe(url="https://a.example.org/u/", bps=20_000.0)
    empty: dict[str, ProbeResult] = {}
    for tput_map in (None, empty):
        scores = score_results([a], tput_map, Weights())
        assert scores[0].throughput_bps is None


def test_failed_throughput_ranks_below_measured_throughput() -> None:
    measured = make_probe(url="https://measured.example.org/u/", bps=90_000.0)
    failed = make_probe(url="https://failed.example.org/u/", bps=90_000.0)
    tput_map = {
        measured.mirror.url: make_probe(url=measured.mirror.url, bps=1_000_000.0),
        failed.mirror.url: make_probe(
            url=failed.mirror.url, bps=None, status=404, error="http_404"
        ),
    }
    scores = score_results([failed, measured], tput_map, Weights())
    assert [s.mirror.host for s in scores] == [
        "measured.example.org",
        "failed.example.org",
    ]
    assert scores[1].throughput_bps is None
    assert scores[1].throughput_probe is not None


def test_skipped_throughput_carries_no_weight() -> None:
    fast = make_probe(url="https://fast.example.org/u/", ttfb_ms=10.0)
    slow = make_probe(url="https://slow.example.org/u/", ttfb_ms=100.0)
    scores = score_results([slow, fast], None, Weights())
    # Latency 0.4 and security 0.2 renormalize to 2/3 and 1/3.
    assert scores[0].mirror.host == "fast.example.org"
    assert scores[0].composite == 1.0
    assert abs(scores[1].composite - 1 / 3) < 1e-9


def test_prefer_https_drops_http_twin_of_a_working_https_mirror() -> None:
    https_ok = make_probe(url="https://a.example.org/debian/")
    http_twin = make_probe(url="http://a.example.org/debian/", tls=None)
    https_dead = make_probe(
        url="https://b.example.org/debian/", status=None, error="ConnectError"
    )
    http_only = make_probe(url="http://b.example.org/debian/", tls=None)
    other_path = make_probe(url="http://a.example.org/other/", tls=None)
    kept = prefer_https([https_ok, http_twin, https_dead, http_only, other_path])
    assert [r.mirror.url for r in kept] == [
        "https://a.example.org/debian/",
        "https://b.example.org/debian/",
        "http://b.example.org/debian/",
        "http://a.example.org/other/",
    ]


_NOW = 1_794_600_000.0


def _synced(
    host: str, sync_time: float | None, *, error: str | None = None
) -> ProbeResult:
    return replace(
        make_probe(url=f"https://{host}.example.org/u/", error=error),
        sync_time=sync_time,
    )


def test_sync_ages_are_relative_to_the_newest_mirror() -> None:
    newest = _NOW - 5 * 86400  # nothing published for five days
    results = [
        _synced("a", newest),
        _synced("b", newest - 3600),
        _synced("unknown", None),
        _synced("failed", newest - 9 * 86400, error="ConnectError"),
    ]
    ages = sync_ages(results, now=_NOW)
    assert ages == {
        "https://a.example.org/u/": 0.0,
        "https://b.example.org/u/": 3600.0,
    }


def test_sync_ages_ignore_a_mirror_dated_in_the_future() -> None:
    results = [
        _synced("a", _NOW - 3600),
        _synced("b", _NOW - 7200),
        _synced("broken", _NOW + 30 * 86400),
    ]
    ages = sync_ages(results, now=_NOW)
    assert ages["https://a.example.org/u/"] == 0.0
    assert ages["https://b.example.org/u/"] == 3600.0
    assert ages["https://broken.example.org/u/"] == 0.0


def test_sync_ages_empty_when_no_mirror_reports_a_time() -> None:
    assert sync_ages([_synced("a", None)], now=_NOW) == {}


def test_drop_stale() -> None:
    results = [_synced("fresh", _NOW), _synced("old", _NOW - 86400 * 3)]
    unknown = _synced("unknown", None)
    ages = sync_ages([*results, unknown], now=_NOW)

    kept = drop_stale([*results, unknown], ages, 36 * 3600)
    assert [r.mirror.host for r in kept] == ["fresh.example.org", "unknown.example.org"]
    # 0 turns the filter off.
    assert len(drop_stale([*results, unknown], ages, 0)) == 3


def test_score_carries_sync_age() -> None:
    a = _synced("a", _NOW)
    b = _synced("b", _NOW - 7200)
    scores = score_results([a, b], None, Weights(), sync_ages([a, b], now=_NOW))
    assert {s.mirror.host: s.sync_age_s for s in scores} == {
        "a.example.org": 0.0,
        "b.example.org": 7200.0,
    }
    assert score_results([a], None, Weights())[0].sync_age_s is None

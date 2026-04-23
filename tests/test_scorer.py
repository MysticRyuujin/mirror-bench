"""Scorer pure-function tests."""

from mirror_bench.benchmark.scorer import filter_for_policy, score_results
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
    # All security features → 3.5
    full = make_probe(
        url="https://x.example.org/u/", tls="TLSv1.3", http="HTTP/2", cert_valid=True
    )
    scores = score_results([full], None, Weights(latency=0, throughput=0, security=1.0))
    assert scores[0].security_score == 3.5

    # http only → 0
    plain = make_probe(
        url="http://x.example.org/u/", tls=None, http="HTTP/1.1", cert_valid=None
    )
    scores = score_results(
        [plain], None, Weights(latency=0, throughput=0, security=1.0)
    )
    assert scores[0].security_score == 0.0

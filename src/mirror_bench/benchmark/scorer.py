"""Weighted composite mirror ranking."""

from typing import TYPE_CHECKING

from mirror_bench.models import ProbeResult, Score, Weights

if TYPE_CHECKING:
    from collections.abc import Iterable

# Maximum security points we can award. See _security_score for the breakdown.
_MAX_SECURITY = 3.5


def score_results(
    latency_results: Iterable[ProbeResult],
    throughput_results: dict[str, ProbeResult] | None,
    weights: Weights,
) -> list[Score]:
    latency_list = [r for r in latency_results if r.ok]
    if not latency_list:
        return []

    weights = weights.normalized()

    # Collect latency numbers from phase 1; throughput numbers from phase 2 when
    # present, otherwise fall back to the latency-phase bytes_per_sec (which is
    # tiny / noisy but still orders the set consistently).
    throughput_map = throughput_results or {}
    latencies = [r.ttfb_ms for r in latency_list if r.ttfb_ms is not None]
    lat_min, lat_max = (min(latencies), max(latencies)) if latencies else (0.0, 0.0)

    throughput_values: list[float] = []
    for r in latency_list:
        tput_probe = throughput_map.get(r.mirror.url)
        if tput_probe is not None and tput_probe.bytes_per_sec is not None:
            throughput_values.append(tput_probe.bytes_per_sec)
        elif r.bytes_per_sec is not None:
            throughput_values.append(r.bytes_per_sec)
    tput_min, tput_max = (
        (min(throughput_values), max(throughput_values))
        if throughput_values
        else (0.0, 0.0)
    )

    scores: list[Score] = []
    for r in latency_list:
        tput_probe = throughput_map.get(r.mirror.url)
        effective_tput = (
            tput_probe.bytes_per_sec
            if tput_probe is not None and tput_probe.bytes_per_sec is not None
            else r.bytes_per_sec
        )

        lat_component = _normalize_inverse(r.ttfb_ms, lat_min, lat_max)
        tput_component = _normalize(effective_tput, tput_min, tput_max)
        sec_raw = _security_score(r, tput_probe)
        sec_component = sec_raw / _MAX_SECURITY

        composite = (
            weights.latency * lat_component
            + weights.throughput * tput_component
            + weights.security * sec_component
        )

        scores.append(
            Score(
                mirror=r.mirror,
                latency_ms=r.ttfb_ms,
                throughput_bps=effective_tput,
                security_score=sec_raw,
                composite=composite,
                probe=r,
                throughput_probe=tput_probe,
            )
        )

    scores.sort(key=lambda s: s.composite, reverse=True)
    return scores


def _normalize(value: float | None, lo: float, hi: float) -> float:
    if value is None or hi <= lo:
        return 0.0 if value is None else 1.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _normalize_inverse(value: float | None, lo: float, hi: float) -> float:
    if value is None or hi <= lo:
        return 0.0 if value is None else 1.0
    # Lower latency = higher score.
    return max(0.0, min(1.0, (hi - value) / (hi - lo)))


def _security_score(probe: ProbeResult, tput_probe: ProbeResult | None) -> float:
    """Additive 0..3.5: HTTPS(1) + TLS1.3(1) + cert_valid(1) + HTTP/2(0.5)."""
    score = 0.0
    if probe.mirror.is_https:
        score += 1.0
    tls_version = probe.tls_version or (tput_probe.tls_version if tput_probe else None)
    if tls_version == "TLSv1.3":
        score += 1.0
    cert = (
        probe.cert_valid
        if probe.cert_valid is not None
        else (tput_probe.cert_valid if tput_probe else None)
    )
    if cert is True:
        score += 1.0
    http_version = probe.http_version or (
        tput_probe.http_version if tput_probe else None
    )
    if http_version in {"HTTP/2", "HTTP/2.0"}:
        score += 0.5
    return score


def filter_for_policy(
    mirrors: Iterable[ProbeResult],
    *,
    https_only: bool,
    tls13_only: bool,
) -> list[ProbeResult]:
    out: list[ProbeResult] = []
    for r in mirrors:
        if https_only and not r.mirror.is_https:
            continue
        if tls13_only and r.tls_version != "TLSv1.3":
            continue
        out.append(r)
    return out

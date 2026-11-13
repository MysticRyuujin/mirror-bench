"""Weighted composite mirror ranking."""

from dataclasses import replace
from typing import TYPE_CHECKING

from mirror_bench.models import ProbeResult, Score, Weights

if TYPE_CHECKING:
    from collections.abc import Iterable

# Maximum security points we can award. See _security_score for the breakdown.
_MAX_SECURITY = 2.5


def score_results(
    latency_results: Iterable[ProbeResult],
    throughput_results: dict[str, ProbeResult] | None,
    weights: Weights,
) -> list[Score]:
    """Rank mirrors. `throughput_results=None` means phase 2 did not run."""
    throughput_map = throughput_results or {}
    # A mirror that sends its payload over plain HTTP is not an HTTPS mirror,
    # whatever its metadata probe did. It must not be ranked as one.
    latency_list = [
        r
        for r in latency_results
        if r.ok and not _downgraded(throughput_map.get(r.mirror.url))
    ]
    if not latency_list:
        return []

    if throughput_results is None:
        # No measurement exists, so throughput must not carry weight.
        weights = replace(weights, throughput=0.0)
    weights = weights.normalized()

    latencies = [r.ttfb_ms for r in latency_list if r.ttfb_ms is not None]
    lat_min, lat_max = (min(latencies), max(latencies)) if latencies else (0.0, 0.0)

    # Only a successful phase 2 probe is a throughput measurement. The 1 KiB
    # latency probe is not: its rate is latency under another name.
    measured = {
        r.mirror.url: bps
        for r in latency_list
        if (bps := _measured_bps(throughput_map.get(r.mirror.url))) is not None
    }
    tput_min, tput_max = (
        (min(measured.values()), max(measured.values())) if measured else (0.0, 0.0)
    )

    scores: list[Score] = []
    for r in latency_list:
        tput_probe = throughput_map.get(r.mirror.url)
        effective_tput = measured.get(r.mirror.url)

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


def _measured_bps(tput_probe: ProbeResult | None) -> float | None:
    if tput_probe is None or not tput_probe.ok:
        return None
    return tput_probe.bytes_per_sec


def _downgraded(tput_probe: ProbeResult | None) -> bool:
    return tput_probe is not None and tput_probe.error == "https_downgrade"


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
    """Additive 0..2.5: HTTPS(1) + TLS1.3(1) + HTTP/2(0.5).

    Certificate validity earns nothing on its own: the client verifies each
    certificate, so every HTTPS mirror that answers has a valid one.
    """
    score = 0.0
    if probe.mirror.is_https:
        score += 1.0
    tls_version = probe.tls_version or (tput_probe.tls_version if tput_probe else None)
    if tls_version == "TLSv1.3":
        score += 1.0
    http_version = probe.http_version or (
        tput_probe.http_version if tput_probe else None
    )
    if http_version in {"HTTP/2", "HTTP/2.0"}:
        score += 0.5
    return score


def prefer_https(results: Iterable[ProbeResult]) -> list[ProbeResult]:
    """Drop an http:// result when the same site answered over https://.

    Debian's list has no scheme data, so discovery offers both. One row for
    each site is enough once the HTTPS one is known to work.
    """
    results_list = list(results)
    https_ok = {
        r.mirror.url.removeprefix("https://")
        for r in results_list
        if r.mirror.is_https and r.ok
    }
    return [
        r
        for r in results_list
        if r.mirror.is_https or r.mirror.url.removeprefix("http://") not in https_ok
    ]


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

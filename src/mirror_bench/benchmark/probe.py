"""Async probe orchestration (two-phase: latency screen, then throughput)."""

import asyncio
import time
from collections.abc import Callable, Iterable
from statistics import median
from typing import TYPE_CHECKING

import httpx

from mirror_bench.benchmark import h3
from mirror_bench.benchmark import tls as tls_mod
from mirror_bench.models import HostInfo, Mirror, ProbeResult

if TYPE_CHECKING:
    from mirror_bench.discovery.base import MirrorDiscoverer

# Phase 1 samples a small ranged window (1 KiB) to keep the latency probe cheap.
_LATENCY_RANGE = "bytes=0-1023"
_LATENCY_MAX_BYTES = 1024
# identity: the body is read raw and parsed for the mirror's sync time.
_LATENCY_HEADERS = {"Range": _LATENCY_RANGE, "Accept-Encoding": "identity"}
_LATENCY_DEADLINE_S = 10.0

# Phase 2 downloads this many bytes max — caps the cost for slow/misbehaving mirrors.
_THROUGHPUT_MAX_BYTES = 5 * 1024 * 1024
_THROUGHPUT_MIN_BYTES = 256 * 1024
_THROUGHPUT_DEADLINE_S = 30.0

_PROBE_ERRORS = (httpx.HTTPError, httpx.InvalidURL, OSError)

ProgressCallback = Callable[[str, int, int], None]


async def latency_screen(
    client: httpx.AsyncClient,
    mirrors: Iterable[Mirror],
    discoverer: MirrorDiscoverer,
    host: HostInfo,
    *,
    concurrency: int = 20,
    samples: int = 3,
    on_progress: ProgressCallback | None = None,
) -> list[ProbeResult]:
    mirror_list = list(mirrors)
    total = len(mirror_list)
    done = 0
    sem = asyncio.Semaphore(concurrency)
    # Pre-sized buffer so concurrent tasks can write to fixed indices without
    # sharing a list append; the `| None` slot is cheap and makes the type honest.
    results: list[ProbeResult | None] = [None] * total

    async def _work(idx: int, mirror: Mirror) -> None:
        nonlocal done
        async with sem:
            results[idx] = await _latency_probe(
                client, mirror, discoverer, host, samples
            )
            done += 1
            if on_progress is not None:
                on_progress("latency", done, total)

    async with asyncio.TaskGroup() as tg:
        for idx, m in enumerate(mirror_list):
            # TaskGroup owns the Task lifecycle; binding to `_` silences
            # mypy's unused-awaitable check without introducing a real keep-alive.
            _ = tg.create_task(_work(idx, m))

    return [r for r in results if r is not None]


async def throughput_test(
    client: httpx.AsyncClient,
    mirrors: Iterable[Mirror],
    discoverer: MirrorDiscoverer,
    host: HostInfo,
    *,
    concurrency: int = 8,
    on_progress: ProgressCallback | None = None,
) -> dict[str, ProbeResult]:
    mirror_list = list(mirrors)
    total = len(mirror_list)
    done = 0
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, ProbeResult] = {}

    async def _work(mirror: Mirror) -> None:
        nonlocal done
        async with sem:
            out[mirror.url] = await _throughput_probe(client, mirror, discoverer, host)
            done += 1
            if on_progress is not None:
                on_progress("throughput", done, total)

    async with asyncio.TaskGroup() as tg:
        for m in mirror_list:
            _ = tg.create_task(_work(m))

    return out


def _is_html(body: bytes | bytearray) -> bool:
    # None of the probed files is HTML; Fedora's repomd.xml starts `<?xml`.
    return bytes(body[:64]).lstrip().lower().startswith((b"<!doctype html", b"<html"))


def _downgraded(mirror: Mirror, resp: httpx.Response) -> bool:
    """Did an HTTPS mirror send any hop of this exchange over plain HTTP?"""
    return mirror.is_https and any(
        r.url.scheme != "https" for r in (*resp.history, resp)
    )


def _failed(
    mirror: Mirror,
    error: str,
    resp: httpx.Response | None = None,
    *,
    bytes_read: int = 0,
) -> ProbeResult:
    tls_version, cert_valid = _tls_fields(mirror, resp)
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=None,
        total_ms=None,
        bytes_read=bytes_read,
        bytes_per_sec=None,
        status=resp.status_code if resp is not None else None,
        http_version=resp.http_version if resp is not None else None,
        tls_version=tls_version,
        cert_valid=cert_valid,
        error=error,
        final_url=str(resp.url) if resp is not None else None,
    )


def _h3_port(resp: httpx.Response) -> int | None:
    # Alt-Svc is only valid from a secure origin, and it describes the origin
    # that answered, which after a redirect is not the listed one.
    if resp.url.scheme != "https":
        return None
    return h3.parse_alt_svc(resp.headers.get("alt-svc"))


def _tls_fields(
    mirror: Mirror, resp: httpx.Response | None
) -> tuple[str | None, bool | None]:
    # An http:// mirror earns no TLS credit even when it redirects to HTTPS:
    # the first hop, which carries the redirect itself, is unprotected.
    if resp is None or not mirror.is_https:
        return (None, None)
    return tls_mod.inspect(resp)


async def _latency_probe(
    client: httpx.AsyncClient,
    mirror: Mirror,
    discoverer: MirrorDiscoverer,
    host: HostInfo,
    samples: int,
) -> ProbeResult:
    url = discoverer.probe_url(mirror, host)
    ttfbs: list[float] = []
    totals: list[float] = []
    last_resp: httpx.Response | None = None
    last_bytes = 0
    last_body = b""
    last_error = "no_samples"

    for _ in range(samples):
        started = time.perf_counter()
        nbytes = 0
        body = bytearray()
        try:
            async with (
                asyncio.timeout(_LATENCY_DEADLINE_S),
                client.stream("GET", url, headers=_LATENCY_HEADERS) as resp,
            ):
                ttfb_s = time.perf_counter() - started
                if _downgraded(mirror, resp):
                    return _failed(mirror, "https_downgrade", resp)
                async for chunk in resp.aiter_raw():
                    nbytes += len(chunk)
                    body += chunk
                    # Only a server that ignored Range sends more than the
                    # window. A ranged reply is read to its end, which keeps
                    # the connection reusable for the next sample.
                    if nbytes > _LATENCY_MAX_BYTES:
                        break
        except TimeoutError:
            last_error = "timeout"
        except _PROBE_ERRORS as exc:
            last_error = type(exc).__name__
        else:
            ttfbs.append(ttfb_s * 1000.0)
            totals.append((time.perf_counter() - started) * 1000.0)
            if resp.is_success and _is_html(body):
                # Some mirrors answer a missing file with 200 and an error page.
                return _failed(mirror, "soft_404", resp)
            last_resp = resp
            last_bytes = nbytes
            last_body = bytes(body[:_LATENCY_MAX_BYTES])
            continue
        # A mirror that fails before any sample succeeds is not worth the
        # remaining connect timeouts.
        if not ttfbs:
            break

    if last_resp is None:
        return _failed(mirror, last_error)

    tls_version, cert_valid = _tls_fields(mirror, last_resp)
    median_total = median(totals)
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=median(ttfbs),
        total_ms=median_total,
        bytes_read=last_bytes,
        bytes_per_sec=(last_bytes / (median_total / 1000.0))
        if median_total > 0
        else None,
        status=last_resp.status_code,
        http_version=last_resp.http_version,
        tls_version=tls_version,
        cert_valid=cert_valid,
        error=None,
        final_url=str(last_resp.url),
        h3_port=_h3_port(last_resp),
        sync_time=discoverer.sync_time(mirror, last_body),
    )


async def _throughput_probe(
    client: httpx.AsyncClient,
    mirror: Mirror,
    discoverer: MirrorDiscoverer,
    host: HostInfo,
) -> ProbeResult:
    url = mirror.url + discoverer.throughput_path(host)
    started = time.perf_counter()
    bytes_read = 0
    first_byte_at: float | None = None
    last_byte_at = started
    resp: httpx.Response | None = None
    try:
        async with (
            asyncio.timeout(_THROUGHPUT_DEADLINE_S),
            client.stream("GET", url) as resp,
        ):
            if _downgraded(mirror, resp):
                return _failed(mirror, "https_downgrade", resp)
            if not (200 <= resp.status_code < 300):
                return _failed(mirror, f"http_{resp.status_code}", resp)
            # Raw bytes: a decoded Content-Encoding would inflate the count.
            async for chunk in resp.aiter_raw():
                last_byte_at = time.perf_counter()
                if first_byte_at is None:
                    first_byte_at = last_byte_at
                bytes_read += len(chunk)
                if bytes_read >= _THROUGHPUT_MAX_BYTES:
                    break
    # TimeoutError is an OSError and httpx timeouts are HTTPErrors, so this
    # clause must come first: a slow or stalled mirror that already delivered
    # enough bytes still has a valid rate.
    except TimeoutError, httpx.TimeoutException:
        if bytes_read < _THROUGHPUT_MIN_BYTES:
            return _failed(mirror, "timeout", resp, bytes_read=bytes_read)
    except _PROBE_ERRORS as exc:
        return _failed(mirror, type(exc).__name__, resp, bytes_read=bytes_read)

    if resp is None or first_byte_at is None:
        return _failed(mirror, "empty_body", resp)
    if bytes_read < _THROUGHPUT_MIN_BYTES:
        # Each throughput file is megabytes long. A complete body this short
        # is an error page or a stub, and its rate would mean nothing.
        return _failed(mirror, "short_body", resp, bytes_read=bytes_read)

    total_s = last_byte_at - started
    # Measure throughput from TTFB to the last byte, skipping connect/TLS overhead,
    # so the number reflects steady-state bandwidth rather than connection setup cost.
    transfer_s = last_byte_at - first_byte_at
    if transfer_s > 0:
        bps: float | None = bytes_read / transfer_s
    elif total_s > 0:
        bps = bytes_read / total_s
    else:
        bps = None

    tls_version, cert_valid = _tls_fields(mirror, resp)
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=(first_byte_at - started) * 1000.0,
        total_ms=total_s * 1000.0,
        bytes_read=bytes_read,
        bytes_per_sec=bps,
        status=resp.status_code,
        http_version=resp.http_version,
        tls_version=tls_version,
        cert_valid=cert_valid,
        error=None,
        final_url=str(resp.url),
    )

"""Async probe orchestration (two-phase: latency screen, then throughput)."""

import asyncio
import time
from collections.abc import Callable, Iterable
from statistics import median
from typing import TYPE_CHECKING

import httpx

from mirror_bench.benchmark import tls as tls_mod
from mirror_bench.models import HostInfo, Mirror, ProbeResult

if TYPE_CHECKING:
    from mirror_bench.discovery.base import MirrorDiscoverer

# Phase 1 samples a small ranged window (1 KiB) to keep the latency probe cheap.
_LATENCY_RANGE = "bytes=0-1023"

# Phase 2 downloads this many bytes max — caps the cost for slow/misbehaving mirrors.
_THROUGHPUT_MAX_BYTES = 5 * 1024 * 1024
_THROUGHPUT_MIN_BYTES = 256 * 1024


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
    lock = asyncio.Lock()

    async def _work(mirror: Mirror) -> None:
        nonlocal done
        async with sem:
            result = await _throughput_probe(client, mirror, discoverer, host)
            async with lock:
                out[mirror.url] = result
                done += 1
            if on_progress is not None:
                on_progress("throughput", done, total)

    async with asyncio.TaskGroup() as tg:
        for m in mirror_list:
            _ = tg.create_task(_work(m))

    return out


async def _latency_probe(
    client: httpx.AsyncClient,
    mirror: Mirror,
    discoverer: MirrorDiscoverer,
    host: HostInfo,
    samples: int,
) -> ProbeResult:
    url = mirror.url + discoverer.probe_path(host)
    ttfbs: list[float] = []
    totals: list[float] = []
    last_status: int | None = None
    last_http: str | None = None
    last_tls: str | None = None
    last_cert: bool | None = None
    last_bytes = 0
    last_error: str | None = None

    for i in range(samples):
        started = time.perf_counter()
        try:
            resp = await client.get(
                url,
                headers={"Range": _LATENCY_RANGE},
                follow_redirects=False,
            )
        except (httpx.HTTPError, OSError) as exc:
            last_error = type(exc).__name__
            continue
        total_s = time.perf_counter() - started
        # httpx doesn't split TTFB / total cleanly for ranged responses; the whole 1KiB
        # body is read by the time .get() returns. Record total for both — it's a tight
        # upper bound on TTFB at this payload size.
        ttfbs.append(total_s * 1000.0)
        totals.append(total_s * 1000.0)
        last_status = resp.status_code
        last_http = resp.http_version
        last_tls, last_cert = tls_mod.inspect(resp)
        last_bytes = len(resp.content)
        last_error = None
        # On the last sample break early; earlier samples warm the connection.
        if i >= samples - 1:
            break

    if not ttfbs:
        return ProbeResult(
            mirror=mirror,
            ttfb_ms=None,
            total_ms=None,
            bytes_read=0,
            bytes_per_sec=None,
            status=last_status,
            http_version=last_http,
            tls_version=last_tls,
            cert_valid=last_cert,
            error=last_error or "no_samples",
        )

    median_ttfb = median(ttfbs)
    median_total = median(totals)
    bps = (last_bytes / (median_total / 1000.0)) if median_total > 0 else None
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=median_ttfb,
        total_ms=median_total,
        bytes_read=last_bytes,
        bytes_per_sec=bps,
        status=last_status,
        http_version=last_http,
        tls_version=last_tls,
        cert_valid=last_cert,
        error=None,
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
    status: int | None = None
    http_version: str | None = None
    tls_version: str | None = None
    cert_valid: bool | None = None
    try:
        async with client.stream("GET", url, follow_redirects=False) as resp:
            status = resp.status_code
            http_version = resp.http_version
            tls_version, cert_valid = tls_mod.inspect(resp)
            if not (200 <= status < 300):
                return ProbeResult(
                    mirror=mirror,
                    ttfb_ms=None,
                    total_ms=None,
                    bytes_read=0,
                    bytes_per_sec=None,
                    status=status,
                    http_version=http_version,
                    tls_version=tls_version,
                    cert_valid=cert_valid,
                    error=f"http_{status}",
                )
            async for chunk in resp.aiter_bytes():
                if first_byte_at is None:
                    first_byte_at = time.perf_counter()
                bytes_read += len(chunk)
                if bytes_read >= _THROUGHPUT_MAX_BYTES:
                    break
    except (httpx.HTTPError, OSError) as exc:
        return ProbeResult(
            mirror=mirror,
            ttfb_ms=None,
            total_ms=None,
            bytes_read=bytes_read,
            bytes_per_sec=None,
            status=status,
            http_version=http_version,
            tls_version=tls_version,
            cert_valid=cert_valid,
            error=type(exc).__name__,
        )

    ended = time.perf_counter()
    total_ms = (ended - started) * 1000.0
    ttfb_ms = (
        ((first_byte_at - started) * 1000.0) if first_byte_at is not None else None
    )

    # Measure throughput from TTFB to end, skipping connect/TLS overhead, so the number
    # reflects steady-state bandwidth rather than connection setup cost.
    if first_byte_at is not None and bytes_read >= _THROUGHPUT_MIN_BYTES:
        transfer_s = ended - first_byte_at
        bps = bytes_read / transfer_s if transfer_s > 0 else None
    elif bytes_read > 0 and total_ms > 0:
        bps = bytes_read / (total_ms / 1000.0)
    else:
        bps = None

    return ProbeResult(
        mirror=mirror,
        ttfb_ms=ttfb_ms,
        total_ms=total_ms,
        bytes_read=bytes_read,
        bytes_per_sec=bps,
        status=status,
        http_version=http_version,
        tls_version=tls_version,
        cert_valid=cert_valid,
        error=None,
    )

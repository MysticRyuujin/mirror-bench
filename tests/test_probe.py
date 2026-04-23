"""Benchmark probe tests."""

import httpx
import pytest
import respx

from mirror_bench.benchmark import probe
from mirror_bench.discovery import get_discoverer
from mirror_bench.models import Mirror
from tests.conftest import make_host


def _mirror(url: str = "https://mirror.example.org/ubuntu/") -> Mirror:
    return Mirror(
        url=url, host="mirror.example.org", country=None, protocols=("https",)
    )


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_success(client: httpx.AsyncClient) -> None:
    url = "https://mirror.example.org/ubuntu/dists/noble/InRelease"
    respx.get(url).respond(206, content=b"x" * 1024)
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu", codename="noble")
    results = await probe.latency_screen(
        client, [_mirror()], discoverer, host, concurrency=1, samples=2
    )
    assert len(results) == 1
    r = results[0]
    assert r.ok
    assert r.ttfb_ms is not None
    assert r.status == 206


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_failure_captured(client: httpx.AsyncClient) -> None:
    respx.get("https://fail.example.org/ubuntu/dists/noble/InRelease").mock(
        side_effect=httpx.ConnectError("boom")
    )
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu", codename="noble")
    results = await probe.latency_screen(
        client,
        [
            Mirror(
                url="https://fail.example.org/ubuntu/",
                host="fail.example.org",
                country=None,
                protocols=("https",),
            )
        ],
        discoverer,
        host,
        concurrency=1,
        samples=1,
    )
    assert len(results) == 1
    r = results[0]
    assert not r.ok
    assert r.error == "ConnectError"


@pytest.mark.asyncio
@respx.mock
async def test_throughput_probe_reads_bytes(client: httpx.AsyncClient) -> None:
    url = "https://mirror.example.org/ubuntu/dists/noble/main/Contents-amd64.gz"
    payload = b"y" * (512 * 1024)  # 512 KiB — enough to exceed min-bytes threshold
    respx.get(url).respond(200, content=payload)
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu", codename="noble")
    out = await probe.throughput_test(
        client, [_mirror()], discoverer, host, concurrency=1
    )
    assert _mirror().url in out
    r = out[_mirror().url]
    assert r.ok
    assert r.bytes_read == len(payload)
    assert r.bytes_per_sec is not None
    assert r.bytes_per_sec > 0


@pytest.mark.asyncio
@respx.mock
async def test_throughput_probe_http_error_not_ok(client: httpx.AsyncClient) -> None:
    url = "https://mirror.example.org/ubuntu/dists/noble/main/Contents-amd64.gz"
    respx.get(url).respond(404, content=b"")
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu", codename="noble")
    out = await probe.throughput_test(
        client, [_mirror()], discoverer, host, concurrency=1
    )
    r = out[_mirror().url]
    assert not r.ok
    assert r.error
    assert r.error.startswith("http_4")


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_multiple_mirrors_concurrent(
    client: httpx.AsyncClient,
) -> None:
    for i in range(5):
        url = f"https://m{i}.example.org/ubuntu/dists/noble/InRelease"
        respx.get(url).respond(206, content=b"x" * 1024)
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu", codename="noble")
    mirrors = [
        Mirror(
            url=f"https://m{i}.example.org/ubuntu/",
            host=f"m{i}.example.org",
            country=None,
            protocols=("https",),
        )
        for i in range(5)
    ]
    results = await probe.latency_screen(
        client, mirrors, discoverer, host, concurrency=3, samples=1
    )
    assert len(results) == 5
    assert all(r.ok for r in results)

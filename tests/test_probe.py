"""Benchmark probe tests."""

import asyncio
import gzip
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from mirror_bench.benchmark import probe, tls, transport
from mirror_bench.discovery import get_discoverer
from mirror_bench.models import Mirror, ProbeResult
from tests.conftest import make_host

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_LATENCY_URL = "https://mirror.example.org/ubuntu/dists/noble-updates/InRelease"
_THROUGHPUT_URL = "https://mirror.example.org/ubuntu/dists/noble/Contents-amd64.gz"
_KIB = 1024


class _ChunkStream(httpx.AsyncByteStream):
    """Body that yields chunks, then optionally stalls or fails."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        stall_s: float = 0.0,
        then: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._stall_s = stall_s
        self._then = then
        self.sent = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.sent += 1
            yield chunk
        if self._stall_s:
            await asyncio.sleep(self._stall_s)
        if self._then is not None:
            raise self._then


def _mirror(url: str = "https://mirror.example.org/ubuntu/") -> Mirror:
    return Mirror(
        url=url, host="mirror.example.org", country=None, protocols=("https",)
    )


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_success(client: httpx.AsyncClient) -> None:
    url = "https://mirror.example.org/ubuntu/dists/noble-updates/InRelease"
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
    respx.get("https://fail.example.org/ubuntu/dists/noble-updates/InRelease").mock(
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
    url = _THROUGHPUT_URL
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
    url = _THROUGHPUT_URL
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
        url = f"https://m{i}.example.org/ubuntu/dists/noble-updates/InRelease"
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


async def _latency(
    client: httpx.AsyncClient, mirror: Mirror, *, samples: int = 1
) -> ProbeResult:
    results = await probe.latency_screen(
        client,
        [mirror],
        get_discoverer("ubuntu"),
        make_host("ubuntu", codename="noble"),
        concurrency=1,
        samples=samples,
    )
    return results[0]


async def _throughput(client: httpx.AsyncClient, mirror: Mirror) -> ProbeResult:
    out = await probe.throughput_test(
        client,
        [mirror],
        get_discoverer("ubuntu"),
        make_host("ubuntu", codename="noble"),
        concurrency=1,
    )
    return out[mirror.url]


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_follows_redirect(client: httpx.AsyncClient) -> None:
    target = "https://edge.example.org/ubuntu/dists/noble-updates/InRelease"
    respx.get(_LATENCY_URL).respond(302, headers={"Location": target})
    respx.get(target).respond(206, content=b"x" * _KIB)
    r = await _latency(client, _mirror())
    assert r.ok
    assert r.status == 206
    assert r.final_url == target


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_redirect_without_target_is_not_ok() -> None:
    respx.get(_LATENCY_URL).respond(301, headers={"Location": _LATENCY_URL})
    async with transport.build_client() as client:
        r = await _latency(client, _mirror())
    assert not r.ok
    assert r.error == "TooManyRedirects"


@pytest.mark.asyncio
@respx.mock
async def test_https_mirror_redirecting_to_http_is_a_downgrade(
    client: httpx.AsyncClient,
) -> None:
    plain = "http://mirror.example.org/ubuntu/dists/noble-updates/InRelease"
    respx.get(_LATENCY_URL).respond(302, headers={"Location": plain})
    respx.get(plain).respond(206, content=b"x" * _KIB)
    r = await _latency(client, _mirror())
    assert not r.ok
    assert r.error == "https_downgrade"

    plain_big = "http://mirror.example.org/ubuntu/dists/noble/Contents-amd64.gz"
    respx.get(_THROUGHPUT_URL).respond(302, headers={"Location": plain_big})
    respx.get(plain_big).respond(200, content=b"y" * (512 * _KIB))
    t = await _throughput(client, _mirror())
    assert not t.ok
    assert t.error == "https_downgrade"


@pytest.mark.asyncio
@respx.mock
async def test_http_mirror_gets_no_tls_credit_from_a_redirect(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_inspect(_resp: httpx.Response) -> tuple[str | None, bool | None]:
        return ("TLSv1.3", True)

    monkeypatch.setattr(tls, "inspect", fake_inspect)
    plain = "http://mirror.example.org/ubuntu/dists/noble-updates/InRelease"
    respx.get(plain).respond(301, headers={"Location": _LATENCY_URL})
    respx.get(_LATENCY_URL).respond(206, content=b"x" * _KIB)

    via_http = await _latency(client, _mirror("http://mirror.example.org/ubuntu/"))
    assert via_http.ok
    assert via_http.tls_version is None
    assert via_http.cert_valid is None

    direct = await _latency(client, _mirror())
    assert direct.tls_version == "TLSv1.3"


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_stops_reading_when_range_is_ignored(
    client: httpx.AsyncClient,
) -> None:
    body = _ChunkStream([b"x" * _KIB] * 100)
    respx.get(_LATENCY_URL).mock(return_value=httpx.Response(200, stream=body))
    r = await _latency(client, _mirror())
    assert r.ok
    assert body.sent == 2
    assert r.bytes_read == 2 * _KIB


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_deadline(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "_LATENCY_DEADLINE_S", 0.05)
    body = _ChunkStream([b"x"], stall_s=5.0)
    respx.get(_LATENCY_URL).mock(return_value=httpx.Response(206, stream=body))
    r = await _latency(client, _mirror())
    assert not r.ok
    assert r.error == "timeout"


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_gives_up_after_first_failure(
    client: httpx.AsyncClient,
) -> None:
    route = respx.get(_LATENCY_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    r = await _latency(client, _mirror(), samples=3)
    assert not r.ok
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_latency_probe_invalid_url_is_captured(
    client: httpx.AsyncClient,
) -> None:
    r = await _latency(client, _mirror("http://mirror.example.org:abc/"))
    assert not r.ok
    assert r.error == "InvalidURL"


@pytest.mark.asyncio
@respx.mock
async def test_throughput_counts_bytes_on_the_wire(client: httpx.AsyncClient) -> None:
    compressed = gzip.compress(b"0" * (4 * _KIB * _KIB))
    respx.get(_THROUGHPUT_URL).respond(
        200, content=compressed, headers={"Content-Encoding": "gzip"}
    )
    r = await _throughput(client, _mirror())
    assert r.ok
    assert r.bytes_read == len(compressed)


@pytest.mark.asyncio
@respx.mock
async def test_throughput_deadline_keeps_a_usable_partial_read(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "_THROUGHPUT_DEADLINE_S", 0.05)
    body = _ChunkStream([b"y" * (64 * _KIB)] * 5, stall_s=5.0)
    respx.get(_THROUGHPUT_URL).mock(return_value=httpx.Response(200, stream=body))
    r = await _throughput(client, _mirror())
    assert r.ok
    assert r.bytes_read == 320 * _KIB
    assert r.bytes_per_sec is not None
    assert r.bytes_per_sec > 0


@pytest.mark.asyncio
@respx.mock
async def test_throughput_deadline_with_too_few_bytes_is_a_timeout(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "_THROUGHPUT_DEADLINE_S", 0.05)
    body = _ChunkStream([b"y" * _KIB], stall_s=5.0)
    respx.get(_THROUGHPUT_URL).mock(return_value=httpx.Response(200, stream=body))
    r = await _throughput(client, _mirror())
    assert not r.ok
    assert r.error == "timeout"
    assert r.bytes_per_sec is None


@pytest.mark.asyncio
@respx.mock
async def test_throughput_stall_keeps_a_usable_partial_read(
    client: httpx.AsyncClient,
) -> None:
    # The transport read timeout fires long before the phase deadline.
    body = _ChunkStream([b"y" * (64 * _KIB)] * 5, then=httpx.ReadTimeout("stalled"))
    respx.get(_THROUGHPUT_URL).mock(return_value=httpx.Response(200, stream=body))
    r = await _throughput(client, _mirror())
    assert r.ok
    assert r.bytes_read == 320 * _KIB
    assert r.bytes_per_sec is not None


@pytest.mark.asyncio
@respx.mock
async def test_throughput_empty_body_is_an_error(client: httpx.AsyncClient) -> None:
    respx.get(_THROUGHPUT_URL).respond(200, content=b"")
    r = await _throughput(client, _mirror())
    assert not r.ok
    assert r.error == "empty_body"


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_records_advertised_http3(
    client: httpx.AsyncClient,
) -> None:
    respx.get(_LATENCY_URL).respond(
        206, content=b"x" * _KIB, headers={"Alt-Svc": 'h3=":443"; ma=3600'}
    )
    r = await _latency(client, _mirror())
    assert r.h3_port == 443


@pytest.mark.asyncio
@respx.mock
async def test_http3_advertisement_over_plain_http_is_ignored(
    client: httpx.AsyncClient,
) -> None:
    plain = "http://mirror.example.org/ubuntu/dists/noble-updates/InRelease"
    respx.get(plain).respond(
        206, content=b"x" * _KIB, headers={"Alt-Svc": 'h3=":443"; ma=3600'}
    )
    r = await _latency(client, _mirror("http://mirror.example.org/ubuntu/"))
    assert r.ok
    assert r.h3_port is None


@pytest.mark.asyncio
@respx.mock
async def test_http3_port_comes_from_the_origin_that_answered(
    client: httpx.AsyncClient,
) -> None:
    target = "https://edge.example.org/ubuntu/dists/noble-updates/InRelease"
    respx.get(_LATENCY_URL).respond(
        302, headers={"Location": target, "Alt-Svc": 'h3=":443"'}
    )
    respx.get(target).respond(
        206, content=b"x" * _KIB, headers={"Alt-Svc": 'h3=":8443"'}
    )
    r = await _latency(client, _mirror())
    assert r.final_url == target
    assert r.h3_port == 8443


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_reads_the_sync_time(client: httpx.AsyncClient) -> None:
    route = respx.get(_LATENCY_URL).respond(
        206, content=b"Origin: Ubuntu\nDate: Fri, 13 Nov 2026  3:21:26 UTC\n"
    )
    r = await _latency(client, _mirror())
    assert r.sync_time == 1794540086.0
    # A compressed body could not be parsed for the date.
    assert route.calls.last.request.headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
@respx.mock
async def test_latency_probe_without_a_sync_time_is_still_ok(
    client: httpx.AsyncClient,
) -> None:
    respx.get(_LATENCY_URL).respond(206, content=b"x" * _KIB)
    r = await _latency(client, _mirror())
    assert r.ok
    assert r.sync_time is None

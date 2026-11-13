"""HTTP/3 discovery and QUIC probe wiring tests."""

import asyncio
import json
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import respx
from aioquic.h3.events import DataReceived, H3Event, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import ConnectionTerminated, ProtocolNegotiated, QuicEvent
from typer.testing import CliRunner

from mirror_bench.benchmark import h3, h3_quic
from mirror_bench.cli import app
from mirror_bench.models import Mirror, ProbeResult
from tests.test_scorer import make_probe

if TYPE_CHECKING:
    from collections.abc import Iterable

    from click.testing import Result

runner = CliRunner()


@pytest.mark.parametrize(
    ("header", "port"),
    [
        (None, None),
        ("", None),
        ('h3=":443"; ma=3600', 443),
        # Fastly: no space after the separators, draft ids after the final one.
        ('h3=":443";ma=86400,h3-29=":443";ma=86400,h3-27=":443";ma=86400', 443),
        ('h3-29=":443"; ma=86400', None),
        ('h2=":443"; ma=60, h3=":8443"; ma=60', 8443),
        ('H3=":443"', 443),
        ("clear", None),
        # An alternative on another host is not the measured mirror.
        ('h3="alt.example.org:443"; ma=60', None),
        ('h3="alt.example.org:443", h3=":4433"', 4433),
        ('h3=":https"', None),
        ("h3", None),
        ('h3=":0"', None),
        ('h3=":65536"', None),
        ('h3=":' + "9" * 5000 + '"', None),
    ],
)
def test_parse_alt_svc(header: str | None, port: int | None) -> None:
    assert h3.parse_alt_svc(header) == port


def test_ensure_available_reports_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A None entry makes the import machinery raise ImportError.
    monkeypatch.setitem(sys.modules, "mirror_bench.benchmark.h3_quic", None)
    with pytest.raises(h3.Http3UnavailableError) as excinfo:
        h3.ensure_available()
    assert excinfo.value.extra == "http3"
    assert "linux-mirror-bench[http3]" in str(excinfo.value)


@respx.mock
def test_http3_flag_without_extra_exits_2_before_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mirror_bench.benchmark.h3_quic", None)
    # No route is mocked: a discovery request would fail the test another way.
    result = runner.invoke(app, ["bench", "--distro", "arch", "--http3"])
    assert result.exit_code == 2
    assert "linux-mirror-bench[http3]" in result.output
    assert not respx.calls


def _mock_two_arch_mirrors() -> None:
    respx.get("https://archlinux.org/mirrors/status/json/").respond(
        200,
        json={
            "urls": [
                {"url": f"https://{name}.example.org/arch/", "active": True}
                for name in ("h3", "plain")
            ]
        },
    )
    respx.get("https://h3.example.org/arch/lastsync").respond(
        206, content=b"1", headers={"Alt-Svc": 'h3=":8443"'}
    )
    respx.get("https://plain.example.org/arch/lastsync").respond(206, content=b"1")


def _run_http3_bench(
    monkeypatch: pytest.MonkeyPatch, h3_result: ProbeResult
) -> tuple[Result, list[tuple[str, int]]]:
    probed: list[tuple[str, int]] = []

    async def fake_probe(mirror: Mirror, url: str, port: int) -> ProbeResult:
        probed.append((url, port))
        return replace(h3_result, mirror=mirror)

    monkeypatch.setattr(h3_quic, "probe", fake_probe)
    _mock_two_arch_mirrors()
    result = runner.invoke(
        app, ["bench", "--distro", "arch", "--no-throughput", "--http3", "--json"]
    )
    return result, probed


@respx.mock
def test_http3_flag_probes_only_mirrors_that_advertise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, probed = _run_http3_bench(
        monkeypatch, make_probe(ttfb_ms=9.0, http="HTTP/3")
    )
    assert result.exit_code == 0, result.output
    assert probed == [("https://h3.example.org/arch/lastsync", 8443)]
    by_host = {r["mirror"]["host"]: r for r in json.loads(result.stdout)["results"]}
    assert by_host["h3.example.org"]["h3_latency_ms"] == 9.0
    assert by_host["plain.example.org"]["h3_latency_ms"] is None
    assert by_host["plain.example.org"]["h3_error"] is None
    assert "UDP may be blocked" not in result.stderr


@respx.mock
def test_http3_flag_notes_blocked_udp_when_no_probe_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run_http3_bench(
        monkeypatch,
        make_probe(ttfb_ms=None, status=None, http="HTTP/3", error="ConnectionError"),
    )
    assert result.exit_code == 0, result.output
    by_host = {r["mirror"]["host"]: r for r in json.loads(result.stdout)["results"]}
    assert by_host["h3.example.org"]["h3_error"] == "ConnectionError"
    assert "UDP may be blocked" in result.stderr


class _FakeHttp:
    """Stands in for H3Connection: turns each QUIC event into scripted events."""

    def __init__(self, script: dict[int, list[H3Event]]) -> None:
        self._script = script
        self.seen: list[QuicEvent] = []

    def handle_event(self, event: QuicEvent) -> list[H3Event]:
        self.seen.append(event)
        return self._script.get(id(event), [])


def _client(script: dict[int, list[H3Event]]) -> tuple[h3_quic._H3Client, _FakeHttp]:
    client = h3_quic._H3Client(QuicConnection(configuration=QuicConfiguration()))
    fake = _FakeHttp(script)
    client.__dict__["_http"] = fake
    return client, fake


@pytest.mark.asyncio
async def test_quic_client_feeds_events_that_arrive_before_the_request() -> None:
    early = ProtocolNegotiated(alpn_protocol="h3")
    client, fake = _client({})
    client.quic_event_received(early)
    assert fake.seen == [early]


@pytest.mark.asyncio
async def test_quic_client_keeps_status_when_trailers_arrive() -> None:
    headers = ProtocolNegotiated(alpn_protocol="h3")
    trailers = ProtocolNegotiated(alpn_protocol="h3")
    client, _ = _client(
        {
            id(headers): [
                HeadersReceived(
                    headers=[(b":status", b"206")], stream_id=0, stream_ended=False
                ),
                DataReceived(data=b"x" * 11, stream_id=0, stream_ended=False),
            ],
            id(trailers): [
                HeadersReceived(
                    headers=[(b"x-checksum", b"1")], stream_id=0, stream_ended=True
                )
            ],
        }
    )
    done: asyncio.Future[h3_quic._Response] = asyncio.get_running_loop().create_future()
    client.__dict__["_done"] = done
    client.quic_event_received(headers)
    first_headers_at = client.__dict__["_response"].headers_at
    client.quic_event_received(trailers)
    response = await done
    assert response.status == 206
    assert response.bytes_read == 11
    assert response.headers_at == first_headers_at


@pytest.mark.asyncio
async def test_quic_client_reports_termination_before_the_request() -> None:
    client, _ = _client({})
    client.quic_event_received(
        ConnectionTerminated(
            error_code=1, frame_type=None, reason_phrase="Idle timeout"
        )
    )
    with pytest.raises(ConnectionError):
        await client.get(b"mirror.example.org", b"/lastsync")


@respx.mock
def test_http3_probes_respect_the_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    async def fake_probe_advertised(
        results: Iterable[ProbeResult], *, concurrency: int
    ) -> dict[str, ProbeResult]:
        seen.append(concurrency)
        return {}

    monkeypatch.setattr(h3, "probe_advertised", fake_probe_advertised)
    _mock_two_arch_mirrors()
    result = runner.invoke(
        app,
        [
            "bench",
            "--distro",
            "arch",
            "--no-throughput",
            "--http3",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == [1]

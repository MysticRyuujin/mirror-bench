"""One ranged GET over HTTP/3 (QUIC). Needs the optional `http3` extra.

This module imports aioquic at load time. Import it only through
`mirror_bench.benchmark.h3`, which turns a missing extra into a clear error.
"""

import asyncio
import ssl
import time
from typing import TYPE_CHECKING

import httpx
from aioquic.asyncio.client import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection, ProtocolError
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.h3.exceptions import H3Error
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnectionError
from aioquic.quic.events import ConnectionTerminated

from mirror_bench.benchmark.transport import USER_AGENT
from mirror_bench.models import Mirror, ProbeResult

if TYPE_CHECKING:
    from aioquic.asyncio.protocol import QuicStreamHandler
    from aioquic.quic.connection import QuicConnection
    from aioquic.quic.events import QuicEvent

_RANGE = b"bytes=0-1023"
_MAX_BYTES = 1024
_DEADLINE_S = 8.0

# aioquic reports protocol failures with its own exception types; OSError
# covers DNS failure, a refused or reset connection, and a host with no IPv6
# socket support.
_PROBE_ERRORS = (OSError, QuicConnectionError, ProtocolError, H3Error)


class _Response:
    def __init__(self) -> None:
        self.status: int | None = None
        self.headers_at: float | None = None
        self.bytes_read = 0


class _H3Client(QuicConnectionProtocol):
    def __init__(
        self, quic: QuicConnection, stream_handler: QuicStreamHandler | None = None
    ) -> None:
        super().__init__(quic, stream_handler)
        self._http = H3Connection(quic)
        self._response = _Response()
        self._error: Exception | None = None
        # Created by get(): a future that fails with nobody awaiting it makes
        # the event loop print "exception was never retrieved".
        self._done: asyncio.Future[_Response] | None = None

    async def get(self, authority: bytes, path: bytes) -> _Response:
        if self._error is not None:
            raise self._error
        stream_id = self._quic.get_next_available_stream_id()
        self._http.send_headers(
            stream_id,
            [
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", authority),
                (b":path", path),
                (b"user-agent", USER_AGENT.encode()),
                (b"range", _RANGE),
            ],
            end_stream=True,
        )
        self.transmit()
        self._done = self._loop.create_future()
        return await self._done

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ConnectionTerminated):
            self._fail(ConnectionError(event.reason_phrase))
            return
        # Every event goes to the HTTP/3 layer, also before a request exists:
        # the peer's control and QPACK streams open with the handshake, and
        # dropping them corrupts the state that later frames depend on.
        # This runs in a transport callback, where a raised error would be
        # logged by the event loop and lost; keep it for the probe.
        try:
            h3_events = self._http.handle_event(event)
        except (ProtocolError, H3Error) as exc:
            self._fail(exc)
            return
        done = self._done
        if done is None or done.done():
            return
        for h3_event in h3_events:
            if isinstance(h3_event, HeadersReceived):
                # Later header blocks are trailers and carry no :status.
                if self._response.headers_at is None:
                    self._response.headers_at = time.perf_counter()
                    status = dict(h3_event.headers).get(b":status", b"")
                    self._response.status = int(status) if status.isdigit() else None
            elif isinstance(h3_event, DataReceived):
                self._response.bytes_read += len(h3_event.data)
            else:
                continue
            # A server that ignored Range sends the whole file; stop there.
            if h3_event.stream_ended or self._response.bytes_read > _MAX_BYTES:
                done.set_result(self._response)
                return

    def _fail(self, exc: Exception) -> None:
        if self._error is None:
            self._error = exc
        if self._done is not None and not self._done.done():
            self._done.set_exception(exc)


def _configuration(host: str) -> QuicConfiguration:
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        idle_timeout=_DEADLINE_S,
        server_name=host,
    )
    # aioquic verifies against certifi by default. Prefer the system store,
    # which is what the HTTP/1.1 and HTTP/2 probes trust.
    paths = ssl.get_default_verify_paths()
    if paths.cafile or paths.capath:
        configuration.load_verify_locations(cafile=paths.cafile, capath=paths.capath)
    return configuration


def _failed(mirror: Mirror, url: str, error: str) -> ProbeResult:
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=None,
        total_ms=None,
        bytes_read=0,
        bytes_per_sec=None,
        status=None,
        http_version="HTTP/3",
        tls_version=None,
        cert_valid=None,
        error=error,
        final_url=url,
    )


async def probe(mirror: Mirror, url: str, port: int) -> ProbeResult:
    """GET the first 1 KiB of `url` over HTTP/3 on `port`.

    The reported time is the request round trip on an established
    connection, which is what the phase 1 median measures for TCP.
    """
    target = httpx.URL(url)
    try:
        # No outer deadline on the handshake: QUIC's idle timeout ends a
        # connection attempt that gets no answer (blocked UDP). Cancelling
        # aioquic's own handshake wait from outside leaves an unretrieved
        # exception behind, which the event loop prints.
        async with connect(
            target.host,
            port,
            configuration=_configuration(target.host),
            create_protocol=_H3Client,
        ) as client:
            if not isinstance(client, _H3Client):
                return _failed(mirror, url, "no_client")
            started = time.perf_counter()
            async with asyncio.timeout(_DEADLINE_S):
                response = await client.get(target.netloc, target.raw_path)
            ended = time.perf_counter()
    except TimeoutError:
        return _failed(mirror, url, "timeout")
    except _PROBE_ERRORS as exc:
        return _failed(mirror, url, type(exc).__name__)

    headers_at = response.headers_at
    return ProbeResult(
        mirror=mirror,
        ttfb_ms=(headers_at - started) * 1000.0 if headers_at is not None else None,
        total_ms=(ended - started) * 1000.0,
        bytes_read=response.bytes_read,
        bytes_per_sec=None,
        status=response.status,
        http_version="HTTP/3",
        # QUIC has no other TLS version, and the handshake verified the chain.
        tls_version="TLSv1.3",
        cert_valid=True,
        error=None,
        final_url=url,
    )

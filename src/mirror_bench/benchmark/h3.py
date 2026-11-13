"""HTTP/3 support: discovery from the Alt-Svc response header (RFC 7838),
and an optional QUIC probe of the mirrors that advertise it.
"""

import asyncio
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mirror_bench.models import ProbeResult

_QUIC_MODULE = "mirror_bench.benchmark.h3_quic"


def parse_alt_svc(header: str | None) -> int | None:
    """Return the port where the responding origin offers HTTP/3, or None.

    Only the final `h3` protocol id counts; draft ids such as `h3-29` are
    obsolete. An alternative on another host is skipped: it is a different
    endpoint from the mirror that was measured.
    """
    if not header:
        return None
    for entry in header.split(","):
        alternative = entry.split(";", 1)[0].strip()
        if alternative.lower() == "clear":
            return None
        protocol, sep, authority = alternative.partition("=")
        if not sep or protocol.strip().lower() != "h3":
            continue
        alt_host, _, port = authority.strip().strip('"').rpartition(":")
        # The length check also keeps int() away from absurd digit strings,
        # which raise instead of returning a number.
        if alt_host or not port.isascii() or not port.isdigit() or len(port) > 5:
            continue
        if 0 < int(port) <= 65535:
            return int(port)
    return None


class Http3UnavailableError(RuntimeError):
    """`--http3` was requested but the optional QUIC dependency is missing."""

    def __init__(self) -> None:
        self.extra = "http3"
        super().__init__(
            "--http3 needs the optional QUIC dependency; "
            'install "linux-mirror-bench[http3]"'
        )


def ensure_available() -> None:
    """Raise Http3UnavailableError unless the QUIC probe can be imported.

    Importing, not only locating, the module also catches an installed but
    broken native dependency.
    """
    try:
        import_module(_QUIC_MODULE)
    except ImportError as exc:
        raise Http3UnavailableError from exc


async def probe_advertised(
    results: Iterable[ProbeResult], *, concurrency: int
) -> dict[str, ProbeResult]:
    """Probe over QUIC each mirror whose latency probe advertised HTTP/3.

    The request goes to the origin that sent the advertisement
    (`final_url`), keyed in the result by the listed mirror URL.
    """
    from mirror_bench.benchmark import h3_quic

    sem = asyncio.Semaphore(concurrency)
    out: dict[str, ProbeResult] = {}

    async def _work(result: ProbeResult, url: str, port: int) -> None:
        async with sem:
            out[result.mirror.url] = await h3_quic.probe(result.mirror, url, port)

    async with asyncio.TaskGroup() as tg:
        for r in results:
            if r.h3_port is not None and r.final_url is not None:
                _ = tg.create_task(_work(r, r.final_url, r.h3_port))

    return out

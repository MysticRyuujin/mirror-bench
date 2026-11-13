"""Base interface for per-distro mirror discoverers."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mirror_bench.models import HostInfo, Mirror

_SWEEP_CONCURRENCY = 8


class DiscoveryError(RuntimeError):
    """Raised when a distro's mirror list cannot be fetched or used."""

    def __init__(self, distro: str, url: str, reason: str) -> None:
        self.distro = distro
        self.url = url
        self.reason = reason
        super().__init__(f"could not discover {distro} mirrors from {url}: {reason}")


class MirrorDiscoverer(ABC):
    """Fetch the list of candidate mirrors for a given distribution."""

    # Identifier matching HostInfo.base_distro_id.
    distro: str

    @abstractmethod
    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        """Return discovered mirrors, optionally filtered to ISO alpha-2 codes."""

    @abstractmethod
    def probe_path(self, host: HostInfo) -> str:
        """Relative path on each mirror used for the phase-1 latency screen."""

    @abstractmethod
    def throughput_path(self, host: HostInfo) -> str:
        """Relative path on each mirror used for the phase-2 throughput test."""


async def fetch(
    client: httpx.AsyncClient,
    distro: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """GET a mirror list that discovery cannot continue without."""
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DiscoveryError(distro, url, f"HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise DiscoveryError(distro, url, type(exc).__name__) from exc
    return resp


async def fetch_all(
    client: httpx.AsyncClient,
    requests: Sequence[tuple[str, dict[str, str] | None]],
) -> list[httpx.Response | None]:
    """GET optional (url, params) lists concurrently, in input order.

    A request that fails yields None. No task raises, so the TaskGroup never
    surfaces an ExceptionGroup to the caller.
    """
    sem = asyncio.Semaphore(_SWEEP_CONCURRENCY)
    results: list[httpx.Response | None] = [None] * len(requests)

    async def _one(idx: int, url: str, params: dict[str, str] | None) -> None:
        async with sem:
            try:
                results[idx] = await client.get(url, params=params)
            except httpx.HTTPError:
                return

    async with asyncio.TaskGroup() as tg:
        for idx, (url, params) in enumerate(requests):
            _ = tg.create_task(_one(idx, url, params))

    return results


def with_https_candidates(mirrors: list[Mirror]) -> list[Mirror]:
    """Add an https:// candidate ahead of each http:// mirror that has none.

    Upstream lists name one scheme for a mirror, and often the http:// one
    for a host that also serves HTTPS. Probing settles it: a candidate that
    does not answer drops out, and `scorer.prefer_https` keeps the https://
    row when both answer.
    """
    urls = {m.url for m in mirrors}
    out: list[Mirror] = []
    for m in mirrors:
        if not m.is_https:
            twin = "https://" + m.url.removeprefix("http://")
            if twin not in urls:
                urls.add(twin)
                out.append(replace(m, url=twin, protocols=("https",)))
        out.append(m)
    return out


def host_of(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url


def ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"

"""Base interface for per-distro mirror discoverers."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import httpx

    from mirror_bench.models import HostInfo, Mirror


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


def host_of(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url


def ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"

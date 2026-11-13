"""Ubuntu mirror discovery via mirrors.ubuntu.com.

mirrors.ubuntu.com/mirrors.txt returns a *single* geo-selected mirror (not the
full list), so without an explicit --country we sweep a default set of mirror-rich
countries to build a representative candidate pool.
"""

from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    fetch,
    fetch_all,
    host_of,
    moving_suite,
    release_date,
    with_https_candidates,
)
from mirror_bench.distro import DEFAULT_CODENAMES
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_FULL_LIST = "http://mirrors.ubuntu.com/mirrors.txt"
_COUNTRY_LIST = "http://mirrors.ubuntu.com/{cc}.txt"

# Used when the caller does not specify --country. Covers most mirror-rich regions
# to give a representative view without scraping Launchpad HTML.
_DEFAULT_COUNTRIES: tuple[str, ...] = (
    "US",
    "CA",
    "GB",
    "DE",
    "FR",
    "NL",
    "SE",
    "IT",
    "ES",
    "PL",
    "BR",
    "AR",
    "JP",
    "KR",
    "CN",
    "IN",
    "AU",
    "NZ",
    "ZA",
)


class UbuntuDiscoverer(MirrorDiscoverer):
    distro = "ubuntu"

    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        targets = [c.upper() for c in (countries or _DEFAULT_COUNTRIES)]
        responses = await fetch_all(
            client, [(_COUNTRY_LIST.format(cc=cc), None) for cc in targets]
        )
        entries: list[tuple[str, str | None]] = []
        for cc, resp in zip(targets, responses, strict=True):
            if resp is not None and resp.status_code == 200:
                entries.extend((u, cc) for u in _parse_list(resp.text))

        # The geo-nearest list has no country data, so it must not stand in for
        # a country the caller asked for.
        if not entries and not countries:
            full = await fetch(client, self.distro, _FULL_LIST)
            entries.extend((u, None) for u in _parse_list(full.text))

        seen: set[str] = set()
        mirrors: list[Mirror] = []
        for url, country in entries:
            if url in seen:
                continue
            seen.add(url)
            mirrors.append(
                Mirror(
                    url=ensure_trailing_slash(url),
                    host=host_of(url),
                    country=country,
                    protocols=("https" if url.startswith("https://") else "http",),
                )
            )
        return with_https_candidates(mirrors)

    def probe_path(self, host: HostInfo) -> str:
        codename = host.codename or DEFAULT_CODENAMES[self.distro]
        return f"dists/{moving_suite(codename)}/InRelease"

    def sync_time(self, mirror: Mirror, body: bytes) -> float | None:
        return release_date(body)

    def throughput_path(self, host: HostInfo) -> str:
        # These lists cover archive mirrors, which carry amd64 and i386 only;
        # other architectures live on ports.ubuntu.com.
        codename = host.codename or DEFAULT_CODENAMES[self.distro]
        return f"dists/{codename}/Contents-amd64.gz"


def _parse_list(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("http://", "https://"))
    ]

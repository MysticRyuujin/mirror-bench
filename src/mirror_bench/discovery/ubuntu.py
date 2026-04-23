"""Ubuntu mirror discovery via mirrors.ubuntu.com.

mirrors.ubuntu.com/mirrors.txt returns a *single* geo-selected mirror (not the
full list), so without an explicit --country we sweep a default set of mirror-rich
countries to build a representative candidate pool.
"""

import httpx

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    host_of,
)
from mirror_bench.models import HostInfo, Mirror

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
        entries: list[tuple[str, str | None]] = []
        targets = countries or _DEFAULT_COUNTRIES
        for country_code in targets:
            try:
                resp = await client.get(_COUNTRY_LIST.format(cc=country_code.upper()))
            except httpx.HTTPError:
                continue
            if resp.status_code == 200:
                entries.extend(
                    (u, country_code.upper()) for u in _parse_list(resp.text)
                )

        # Fallback: if per-country sweep returned nothing, use the geo-nearest URL.
        if not entries:
            resp = await client.get(_FULL_LIST)
            resp.raise_for_status()
            entries.extend((u, None) for u in _parse_list(resp.text))

        seen: set[str] = set()
        mirrors: list[Mirror] = []
        for url, cc in entries:
            if url in seen:
                continue
            seen.add(url)
            mirrors.append(
                Mirror(
                    url=ensure_trailing_slash(url),
                    host=host_of(url),
                    country=cc,
                    protocols=_protocols_from(url),
                )
            )
        return mirrors

    def probe_path(self, host: HostInfo) -> str:
        codename = host.codename or "noble"
        return f"dists/{codename}/InRelease"

    def throughput_path(self, host: HostInfo) -> str:
        codename = host.codename or "noble"
        return f"dists/{codename}/main/Contents-{host.apt_arch}.gz"


def _parse_list(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _protocols_from(url: str) -> tuple[str, ...]:
    if url.startswith("https://"):
        return ("https",)
    if url.startswith("http://"):
        return ("http",)
    return ()

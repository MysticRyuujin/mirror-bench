"""Debian mirror discovery via Mirrors.masterlist."""

from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    fetch,
)
from mirror_bench.distro import DEFAULT_CODENAMES
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_MASTERLIST = "https://mirror-master.debian.org/status/Mirrors.masterlist"


class DebianDiscoverer(MirrorDiscoverer):
    distro = "debian"

    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        resp = await fetch(client, self.distro, _MASTERLIST)
        records = _parse_masterlist(resp.text)
        wanted_cc = {c.upper() for c in countries}
        mirrors: list[Mirror] = []
        seen: set[str] = set()
        for rec in records:
            site = rec.get("Site")
            archive_path = rec.get("Archive-http")
            if not site or not archive_path:
                continue
            country_parts = rec.get("Country", "").split()
            country = country_parts[0].upper() if country_parts else None
            if wanted_cc and (country is None or country not in wanted_cc):
                continue
            arches = rec.get("Archive-architecture", "").split()
            if arches and host.apt_arch not in arches:
                continue
            # The masterlist records only an HTTP path and does not say which
            # sites also serve HTTPS, so both schemes are candidates.
            for scheme in ("https", "http"):
                url = ensure_trailing_slash(f"{scheme}://{site}{archive_path}")
                if url in seen:
                    continue
                seen.add(url)
                mirrors.append(
                    Mirror(url=url, host=site, country=country, protocols=(scheme,))
                )
        return mirrors

    def probe_path(self, host: HostInfo) -> str:
        codename = host.codename or DEFAULT_CODENAMES[self.distro]
        return f"dists/{codename}/InRelease"

    def throughput_path(self, host: HostInfo) -> str:
        codename = host.codename or DEFAULT_CODENAMES[self.distro]
        return f"dists/{codename}/main/Contents-{host.apt_arch}.gz"


def _parse_masterlist(text: str) -> list[dict[str, str]]:
    """Parse RFC822-style multi-record format with blank-line separators."""
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records

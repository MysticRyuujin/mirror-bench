"""Debian mirror discovery via Mirrors.masterlist."""

from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    host_of,
)
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
        resp = await client.get(_MASTERLIST)
        resp.raise_for_status()
        records = _parse_masterlist(resp.text)
        wanted_cc = {c.upper() for c in countries}
        mirrors: list[Mirror] = []
        seen: set[str] = set()
        for rec in records:
            site = rec.get("Site")
            if not site:
                continue
            country = (rec.get("Country") or "").split()[0].upper() or None
            if wanted_cc and (country is None or country not in wanted_cc):
                continue
            archive_path = rec.get("Archive-http") or rec.get("Archive-https")
            if not archive_path:
                continue
            scheme = "https" if "Archive-https" in rec else "http"
            url = f"{scheme}://{site}{archive_path}"
            if url in seen:
                continue
            seen.add(url)
            protocols = tuple(
                p for p in ("https", "http", "rsync") if rec.get(f"Archive-{p}")
            )
            mirrors.append(
                Mirror(
                    url=ensure_trailing_slash(url),
                    host=host_of(url),
                    country=country,
                    protocols=protocols or (scheme,),
                )
            )
        return mirrors

    def probe_path(self, host: HostInfo) -> str:
        codename = host.codename or "bookworm"
        return f"dists/{codename}/InRelease"

    def throughput_path(self, host: HostInfo) -> str:
        codename = host.codename or "bookworm"
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

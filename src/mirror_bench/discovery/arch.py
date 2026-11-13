"""Arch Linux mirror discovery via archlinux.org/mirrors/status/json/."""

from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    DiscoveryError,
    MirrorDiscoverer,
    ensure_trailing_slash,
    fetch,
    host_of,
)
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_STATUS_JSON = "https://archlinux.org/mirrors/status/json/"


class ArchDiscoverer(MirrorDiscoverer):
    distro = "arch"

    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        resp = await fetch(client, self.distro, _STATUS_JSON)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DiscoveryError(self.distro, _STATUS_JSON, "invalid JSON") from exc
        wanted_cc = {c.upper() for c in countries}
        seen: set[str] = set()
        mirrors: list[Mirror] = []
        for entry in payload.get("urls", []):
            if not entry.get("active"):
                continue
            url = entry.get("url")
            # The status list also carries rsync:// entries.
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            country = (entry.get("country_code") or "").upper() or None
            if wanted_cc and (country is None or country not in wanted_cc):
                continue
            if url in seen:
                continue
            seen.add(url)
            protocol = "https" if url.startswith("https://") else "http"
            mirrors.append(
                Mirror(
                    url=ensure_trailing_slash(url),
                    host=host_of(url),
                    country=country,
                    protocols=(protocol,),
                )
            )
        return mirrors

    def probe_path(self, host: HostInfo) -> str:
        return "lastsync"

    def throughput_path(self, host: HostInfo) -> str:
        # Official Arch mirrors carry x86_64 only, whatever the probing host is.
        return "extra/os/x86_64/extra.db"

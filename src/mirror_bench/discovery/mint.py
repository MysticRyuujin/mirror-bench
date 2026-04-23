"""Linux Mint mirror discovery via HTML scrape of linuxmint.com/mirrors.php.

Mint's page has two tables — "Download mirrors" (ISO-only) and "Repository
mirrors" (apt package mirrors). We want the second one. Each row is:

    <td><img src=".../flags/<cc>.png" alt="<Country Name>"/>...</td>
    <td><name></td>
    <td>https://example.org/linuxmint/</td>

URLs are bare text inside the third `<td>`, not wrapped in `<a href=…>`.
Country is encoded in the flag image filename (ISO 3166-1 alpha-2, lowercase).
"""

import re
from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    host_of,
)
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_MIRRORS_PAGE = "https://www.linuxmint.com/mirrors.php"

_SECTION_RE = re.compile(
    r"Repository mirrors</h2>(.*?)(?:</section>|<h2|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_FLAG_RE = re.compile(
    r'src="[^"]*flags/([a-z_]+)\.(?:png|svg)"',
    re.IGNORECASE,
)
_URL_IN_TD_RE = re.compile(
    r"<td[^>]*>\s*(https?://[^\s<]+?)\s*(?:</a>|</td>)",
    re.IGNORECASE,
)


class MintDiscoverer(MirrorDiscoverer):
    distro = "mint"

    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        resp = await client.get(_MIRRORS_PAGE)
        resp.raise_for_status()
        wanted_cc = {c.upper() for c in countries}
        seen: set[str] = set()
        mirrors: list[Mirror] = []
        for country, url in _parse_repository_rows(resp.text):
            if url in seen:
                continue
            seen.add(url)
            if wanted_cc and (country is None or country not in wanted_cc):
                continue
            proto = "https" if url.startswith("https://") else "http"
            mirrors.append(
                Mirror(
                    url=ensure_trailing_slash(url),
                    host=host_of(url),
                    country=country,
                    protocols=(proto,),
                )
            )
        return mirrors

    def probe_path(self, host: HostInfo) -> str:
        codename = host.codename or "wilma"
        return f"dists/{codename}/InRelease"

    def throughput_path(self, host: HostInfo) -> str:
        codename = host.codename or "wilma"
        return f"dists/{codename}/main/Contents-{host.apt_arch}.gz"


def _parse_repository_rows(html: str) -> list[tuple[str | None, str]]:
    """Yield (iso_alpha2_upper_or_None, url) from the Repository mirrors table."""
    section_match = _SECTION_RE.search(html)
    if not section_match:
        return []
    section = section_match.group(1)
    out: list[tuple[str | None, str]] = []
    for row in _ROW_RE.findall(section):
        flag = _FLAG_RE.search(row)
        country: str | None = None
        if flag:
            code = flag.group(1).lower()
            # Flag filenames for region-agnostic rows are non-ISO (e.g.
            # `_united_nations.png` for "World"). Skip those — the CLI's
            # --country filter is per real country.
            if not code.startswith("_") and len(code) == 2:
                country = code.upper()
        url_match = _URL_IN_TD_RE.search(row)
        if url_match:
            out.append((country, url_match.group(1).strip()))
    return out

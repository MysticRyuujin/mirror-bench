"""Fedora mirror discovery via MirrorManager's mirrorlist endpoint.

The `mirrorlist` endpoint takes `country=` as a filter input but returns a
flat, untagged URL list. Two quirks inform this implementation:

1. Passing a country with no matching mirrors makes Fedora silently augment
   the response with geo-detected neighbors + the global list. The leading
   `# country = global` comment line is the tell; we skip those queries.
2. A single global query has no per-URL country data.

So for `--country <list>` we query once per country and tag each batch. For
the no-country case we fetch the global list (so we don't lose mirrors in
uncovered countries), then sweep a default country set to *overlay* country
tags onto each URL, skipping queries that hit the global fallback.
"""

from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    MirrorDiscoverer,
    ensure_trailing_slash,
    host_of,
)
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_MIRRORLIST = "https://mirrors.fedoraproject.org/mirrorlist"

# Covers most Fedora mirror geography. Each miss adds one HTTP roundtrip; we
# swallow the cost once at discovery time so the table shows useful CC info.
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
    "CZ",
    "AT",
    "CH",
    "BR",
    "AR",
    "JP",
    "KR",
    "CN",
    "TW",
    "IN",
    "AU",
    "NZ",
    "ZA",
    "RU",
    "UA",
)


class FedoraDiscoverer(MirrorDiscoverer):
    distro = "fedora"

    async def discover(
        self,
        client: httpx.AsyncClient,
        host: HostInfo,
        countries: tuple[str, ...] = (),
    ) -> list[Mirror]:
        releasever = host.release_version or "41"
        base_params: dict[str, str] = {
            "repo": f"fedora-{releasever}",
            "arch": host.arch,
        }

        if countries:
            return await _per_country(client, base_params, countries)
        return await _global_with_country_overlay(client, base_params)

    def probe_path(self, host: HostInfo) -> str:
        return "repodata/repomd.xml"

    def throughput_path(self, host: HostInfo) -> str:
        # Reuse repomd.xml: real throughput for Fedora would require parsing
        # repomd.xml per-mirror to find primary.xml.gz. Accepting the
        # latency-biased measurement for now.
        return "repodata/repomd.xml"


async def _per_country(
    client: httpx.AsyncClient,
    base_params: dict[str, str],
    countries: tuple[str, ...],
) -> list[Mirror]:
    seen: set[str] = set()
    mirrors: list[Mirror] = []
    for cc in countries:
        params = {**base_params, "country": cc.lower()}
        resp = await client.get(_MIRRORLIST, params=params)
        if resp.status_code != 200 or not _response_honored_country(resp.text, cc):
            continue
        for url in _parse_mirrorlist(resp.text):
            if url in seen:
                continue
            seen.add(url)
            mirrors.append(_make_mirror(url, cc.upper()))
    return mirrors


async def _global_with_country_overlay(
    client: httpx.AsyncClient,
    base_params: dict[str, str],
) -> list[Mirror]:
    # Build the authoritative URL set first so we don't lose mirrors in
    # countries outside the default sweep.
    resp = await client.get(_MIRRORLIST, params=base_params)
    resp.raise_for_status()
    global_urls = _parse_mirrorlist(resp.text)

    country_by_url: dict[str, str] = {}
    for cc in _DEFAULT_COUNTRIES:
        params = {**base_params, "country": cc.lower()}
        cr = await client.get(_MIRRORLIST, params=params)
        if cr.status_code != 200 or not _response_honored_country(cr.text, cc):
            continue
        for url in _parse_mirrorlist(cr.text):
            # First country claiming a URL wins; stable across reruns.
            country_by_url.setdefault(url, cc.upper())

    mirrors: list[Mirror] = []
    seen: set[str] = set()
    for url in global_urls:
        if url in seen:
            continue
        seen.add(url)
        mirrors.append(_make_mirror(url, country_by_url.get(url)))
    return mirrors


def _response_honored_country(text: str, requested_cc: str) -> bool:
    """Did Fedora actually return mirrors for `requested_cc`?

    When a country has no matching mirrors, Fedora silently substitutes
    neighbors (e.g. `country = gb` → responds with `country = UA DE RO`) or
    augments with `country = global`. The leading `# … country = …` comment
    echoes the countries actually served; we accept the response only when
    the requested code is among them.
    """
    wanted = requested_cc.lower()
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lower = line.lower()
        if "country =" in lower or "country=" in lower:
            # Extract each `country = XX` token.
            served = {
                tok.strip()
                for tok in lower.replace("country=", "country =").split("country =")[1:]
            }
            served = {t.split()[0] for t in served if t.split()}
            return wanted in served
    return False


def _make_mirror(url: str, country: str | None) -> Mirror:
    proto = "https" if url.startswith("https://") else "http"
    return Mirror(
        url=ensure_trailing_slash(url),
        host=host_of(url),
        country=country,
        protocols=(proto,),
    )


def _parse_mirrorlist(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")):
            out.append(line)
    return out

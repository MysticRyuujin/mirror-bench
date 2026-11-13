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

import re
from typing import TYPE_CHECKING

from mirror_bench.discovery.base import (
    DiscoveryError,
    MirrorDiscoverer,
    ensure_trailing_slash,
    fetch,
    fetch_all,
    first_int,
    host_of,
    with_https_candidates,
)
from mirror_bench.models import HostInfo, Mirror

if TYPE_CHECKING:
    import httpx

_MIRRORLIST = "https://mirrors.fedoraproject.org/mirrorlist"

_DEFAULT_RELEASE = "45"
_REVISION_RE = re.compile(rb"<revision>(\d+)</revision>")
_RELEASE_TREE_RE = re.compile(r"/releases/[^/]+/Everything/[^/]+/os/\Z")

# Covers most Fedora mirror geography. Each miss adds one HTTP roundtrip; we
# pay the cost once at discovery time so the table shows useful CC info.
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
        repo = f"fedora-{host.release_version or _DEFAULT_RELEASE}"
        base_params: dict[str, str] = {"repo": repo, "arch": host.arch}

        if countries:
            mirrors = await _per_country(client, base_params, countries)
        else:
            mirrors = await _global_with_country_overlay(client, base_params)
        return with_https_candidates(mirrors)

    def probe_path(self, host: HostInfo) -> str:
        # The release tree never changes, so its metadata cannot show that a
        # mirror stopped syncing. The updates tree is rewritten on each push.
        # Mirror URLs end in releases/<ver>/Everything/<arch>/os/; the updates
        # tree is a sibling of releases/.
        release = host.release_version or _DEFAULT_RELEASE
        return (
            f"../../../../../updates/{release}/Everything/{host.arch}"
            "/repodata/repomd.xml"
        )

    def probe_url(self, mirror: Mirror, host: HostInfo) -> str:
        if _in_release_tree(mirror):
            return mirror.url + self.probe_path(host)
        # An unusual layout: the updates tree cannot be located from this
        # URL, so probe the listed repository and report no sync time.
        return mirror.url + "repodata/repomd.xml"

    def sync_time(self, mirror: Mirror, body: bytes) -> float | None:
        if not _in_release_tree(mirror):
            return None
        return first_int(body, _REVISION_RE)

    def throughput_path(self, host: HostInfo) -> str:
        # A large file with a fixed name for the life of a release. repodata
        # payloads have hashed names that differ between mirror sync states.
        return "images/install.img"


def _in_release_tree(mirror: Mirror) -> bool:
    return _RELEASE_TREE_RE.search(mirror.url) is not None


async def _country_responses(
    client: httpx.AsyncClient,
    base_params: dict[str, str],
    countries: tuple[str, ...],
) -> list[tuple[str, str]]:
    """Return (CC, body) for each country MirrorManager really served."""
    responses = await fetch_all(
        client,
        [(_MIRRORLIST, {**base_params, "country": cc.lower()}) for cc in countries],
    )
    out: list[tuple[str, str]] = []
    for cc, resp in zip(countries, responses, strict=True):
        if resp is None or resp.status_code != 200:
            continue
        _check_repo(resp.text, base_params["repo"])
        if _response_honored_country(resp.text, cc):
            out.append((cc.upper(), resp.text))
    return out


async def _per_country(
    client: httpx.AsyncClient,
    base_params: dict[str, str],
    countries: tuple[str, ...],
) -> list[Mirror]:
    seen: set[str] = set()
    mirrors: list[Mirror] = []
    for cc, text in await _country_responses(client, base_params, countries):
        for url in _parse_mirrorlist(text):
            if url in seen:
                continue
            seen.add(url)
            mirrors.append(_make_mirror(url, cc))
    return mirrors


async def _global_with_country_overlay(
    client: httpx.AsyncClient,
    base_params: dict[str, str],
) -> list[Mirror]:
    # Build the authoritative URL set first so we don't lose mirrors in
    # countries outside the default sweep.
    resp = await fetch(client, "fedora", _MIRRORLIST, params=base_params)
    _check_repo(resp.text, base_params["repo"])
    global_urls = _parse_mirrorlist(resp.text)

    country_by_url: dict[str, str] = {}
    for cc, text in await _country_responses(client, base_params, _DEFAULT_COUNTRIES):
        for url in _parse_mirrorlist(text):
            # First country claiming a URL wins; stable across reruns.
            country_by_url.setdefault(url, cc)

    mirrors: list[Mirror] = []
    seen: set[str] = set()
    for url in global_urls:
        if url in seen:
            continue
        seen.add(url)
        mirrors.append(_make_mirror(url, country_by_url.get(url)))
    return mirrors


def _check_repo(text: str, requested_repo: str) -> None:
    """Reject a response for a repo other than the one requested.

    MirrorManager answers an unreleased version with `repo = rawhide`, and an
    unknown one with an `error:` header and no mirrors. Both arrive as HTTP 200.
    """
    header = text.partition("\n")[0].lower()
    if not header.startswith("#"):
        return
    if "error:" in header:
        raise DiscoveryError("fedora", _MIRRORLIST, f"no such repo {requested_repo!r}")
    tokens = header.replace("=", " = ").split()
    if "repo" not in tokens:
        return
    served = tokens[tokens.index("repo") + 2 : tokens.index("repo") + 3]
    if served and served[0] != requested_repo.lower():
        raise DiscoveryError(
            "fedora",
            _MIRRORLIST,
            f"asked for {requested_repo!r}, mirror list is for {served[0]!r}",
        )


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

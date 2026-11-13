"""Per-distro mirror discoverer tests (respx-mocked)."""

from pathlib import Path

import httpx
import pytest
import respx

from mirror_bench.discovery import DiscoveryError, get_discoverer
from mirror_bench.discovery.base import with_https_candidates
from mirror_bench.models import Mirror
from tests.conftest import make_host

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_default_sweep_falls_back_to_full_list(
    client: httpx.AsyncClient,
) -> None:
    # Per-country URLs all return 404 -> discoverer falls back to mirrors.txt.
    respx.get(url__regex=r"http://mirrors\.ubuntu\.com/[A-Z]{2}\.txt").respond(404)
    respx.get("http://mirrors.ubuntu.com/mirrors.txt").respond(
        200, text=(FIXTURES / "ubuntu_mirrors.txt").read_text()
    )
    discoverer = get_discoverer("ubuntu")
    host = make_host("ubuntu")
    mirrors = await discoverer.discover(client, host)
    # Two of the three are listed as http:// and gain an https:// candidate.
    assert len(mirrors) == 5
    hosts = {m.host for m in mirrors}
    assert hosts == {
        "mirror.example-a.org",
        "mirror.example-b.org",
        "mirror.example-c.org",
    }
    https_count = sum(1 for m in mirrors if m.is_https)
    assert https_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_default_sweep_aggregates_countries(
    client: httpx.AsyncClient,
) -> None:
    # Any country returning 200 is aggregated; unknown/404 ones are skipped.
    respx.get("http://mirrors.ubuntu.com/US.txt").respond(
        200, text="http://mirror.us-a.example.org/ubuntu/\n"
    )
    respx.get("http://mirrors.ubuntu.com/DE.txt").respond(
        200, text="https://mirror.de-a.example.org/ubuntu/\n"
    )
    respx.get(url__regex=r"http://mirrors\.ubuntu\.com/[A-Z]{2}\.txt").respond(404)
    discoverer = get_discoverer("ubuntu")
    mirrors = await discoverer.discover(client, make_host("ubuntu"))
    countries = {m.country for m in mirrors}
    assert countries == {"US", "DE"}


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_country_filter() -> None:
    respx.get("http://mirrors.ubuntu.com/US.txt").respond(
        200, text="http://mirror.us-a.example.org/ubuntu/\n"
    )
    respx.get("http://mirrors.ubuntu.com/CA.txt").respond(
        200, text="https://mirror.ca-a.example.org/ubuntu/\n"
    )
    async with httpx.AsyncClient() as c:
        discoverer = get_discoverer("ubuntu")
        mirrors = await discoverer.discover(c, make_host("ubuntu"), ("US", "CA"))
    assert {m.country for m in mirrors} == {"US", "CA"}
    assert [m.url for m in mirrors] == [
        "https://mirror.us-a.example.org/ubuntu/",
        "http://mirror.us-a.example.org/ubuntu/",
        "https://mirror.ca-a.example.org/ubuntu/",
    ]


_DEBIAN_MASTERLIST = "https://mirror-master.debian.org/status/Mirrors.masterlist"


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_country_with_no_mirrors_does_not_fall_back(
    client: httpx.AsyncClient,
) -> None:
    respx.get("http://mirrors.ubuntu.com/IS.txt").respond(404)
    fallback = respx.get("http://mirrors.ubuntu.com/mirrors.txt").respond(
        200, text="http://geo.example.org/ubuntu/\n"
    )
    discoverer = get_discoverer("ubuntu")
    mirrors = await discoverer.discover(client, make_host("ubuntu"), ("IS",))
    assert mirrors == []
    assert not fallback.called


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_drops_lines_that_are_not_urls(client: httpx.AsyncClient) -> None:
    respx.get("http://mirrors.ubuntu.com/US.txt").respond(
        200, text="<html>error</html>\n# note\nhttp://mirror.us-a.example.org/ubuntu/\n"
    )
    discoverer = get_discoverer("ubuntu")
    mirrors = await discoverer.discover(client, make_host("ubuntu"), ("US",))
    assert {m.host for m in mirrors} == {"mirror.us-a.example.org"}


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_survives_one_failed_country(client: httpx.AsyncClient) -> None:
    respx.get("http://mirrors.ubuntu.com/US.txt").mock(
        side_effect=httpx.ConnectError("boom")
    )
    respx.get("http://mirrors.ubuntu.com/CA.txt").respond(
        200, text="https://mirror.ca-a.example.org/ubuntu/\n"
    )
    discoverer = get_discoverer("ubuntu")
    mirrors = await discoverer.discover(client, make_host("ubuntu"), ("US", "CA"))
    assert [m.country for m in mirrors] == ["CA"]


@pytest.mark.asyncio
@respx.mock
async def test_ubuntu_fallback_failure_is_a_discovery_error(
    client: httpx.AsyncClient,
) -> None:
    respx.get(url__regex=r"http://mirrors\.ubuntu\.com/[A-Z]{2}\.txt").respond(404)
    respx.get("http://mirrors.ubuntu.com/mirrors.txt").respond(503)
    discoverer = get_discoverer("ubuntu")
    with pytest.raises(DiscoveryError) as excinfo:
        await discoverer.discover(client, make_host("ubuntu"))
    assert excinfo.value.distro == "ubuntu"
    assert excinfo.value.reason == "HTTP 503"


@pytest.mark.asyncio
@respx.mock
async def test_debian_masterlist(client: httpx.AsyncClient) -> None:
    respx.get(_DEBIAN_MASTERLIST).respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(client, make_host("debian", codename="trixie"))
    # The list has no scheme data: each archive site is an https and an http
    # candidate. The CD-image-only site has no archive and is left out.
    assert {m.host for m in mirrors} == {
        "deb.example.org",
        "mirror.alpha.example.org",
        "mirror.beta.example.org",
        "mirror.gamma.example.org",
    }
    assert len(mirrors) == 8
    assert sum(1 for m in mirrors if m.is_https) == 4
    urls = {m.url for m in mirrors}
    assert "https://mirror.gamma.example.org/pub/linux/debian/" in urls
    assert "http://mirror.gamma.example.org/pub/linux/debian/" in urls


@pytest.mark.asyncio
@respx.mock
async def test_debian_record_without_country(client: httpx.AsyncClient) -> None:
    respx.get(_DEBIAN_MASTERLIST).respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(client, make_host("debian", codename="trixie"))
    geo = [m for m in mirrors if m.host == "deb.example.org"]
    assert len(geo) == 2
    assert all(m.country is None for m in geo)


@pytest.mark.asyncio
@respx.mock
async def test_debian_country_filter(client: httpx.AsyncClient) -> None:
    respx.get(_DEBIAN_MASTERLIST).respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(
        client, make_host("debian", codename="trixie"), ("DE",)
    )
    assert {m.host for m in mirrors} == {"mirror.beta.example.org"}
    assert all(m.country == "DE" for m in mirrors)


@pytest.mark.asyncio
@respx.mock
async def test_debian_architecture_filter(client: httpx.AsyncClient) -> None:
    respx.get(_DEBIAN_MASTERLIST).respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(
        client, make_host("debian", codename="trixie", arch="aarch64")
    )
    assert {m.host for m in mirrors} == {"deb.example.org", "mirror.alpha.example.org"}


@pytest.mark.asyncio
@respx.mock
async def test_debian_list_unavailable_is_a_discovery_error(
    client: httpx.AsyncClient,
) -> None:
    respx.get(_DEBIAN_MASTERLIST).mock(side_effect=httpx.ConnectError("boom"))
    discoverer = get_discoverer("debian")
    with pytest.raises(DiscoveryError) as excinfo:
        await discoverer.discover(client, make_host("debian"))
    assert excinfo.value.reason == "ConnectError"


@pytest.mark.asyncio
@respx.mock
async def test_fedora_global_sweep_overlays_country(client: httpx.AsyncClient) -> None:
    global_body = (
        "# repo = fedora-41 arch = x86_64\n"
        "https://us.example.org/fedora/41/os/\n"
        "https://de.example.org/fedora/41/os/\n"
        "https://liechtenstein.example.org/fedora/41/os/\n"
    )
    # Respx matches routes in registration order; register the most specific
    # first so country-tagged responses win over the catch-all fallback.
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "us"},
    ).respond(200, text="# country = us\nhttps://us.example.org/fedora/41/os/\n")
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "de"},
    ).respond(200, text="# country = de\nhttps://de.example.org/fedora/41/os/\n")
    # Fallback for every other country in the default sweep: no matching
    # country in the comment → detection logic skips it.
    fallback_body = (
        "# repo = fedora-41 country = unrelated\nhttps://us.example.org/fedora/41/os/\n"
    )
    respx.get(
        url__regex=r"https://mirrors\.fedoraproject\.org/mirrorlist\?.*country=",
    ).respond(200, text=fallback_body)
    # Final: the no-country (global) query with all three URLs.
    respx.get("https://mirrors.fedoraproject.org/mirrorlist").respond(
        200, text=global_body
    )

    discoverer = get_discoverer("fedora")
    mirrors = await discoverer.discover(
        client, make_host("fedora", codename=None, release_version="41")
    )
    by_host = {m.host: m.country for m in mirrors}
    assert by_host == {
        "us.example.org": "US",
        "de.example.org": "DE",
        "liechtenstein.example.org": None,  # not in default sweep
    }


@pytest.mark.asyncio
@respx.mock
async def test_fedora_per_country_tags_results(client: httpx.AsyncClient) -> None:
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "us"},
    ).respond(200, text="# country = us\nhttps://us.example.org/fedora/41/os/\n")
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "de"},
    ).respond(200, text="# country = de\nhttps://de.example.org/fedora/41/os/\n")
    discoverer = get_discoverer("fedora")
    mirrors = await discoverer.discover(
        client,
        make_host("fedora", codename=None, release_version="41"),
        ("US", "DE"),
    )
    by_country = {m.country: m.host for m in mirrors}
    assert by_country == {
        "US": "us.example.org",
        "DE": "de.example.org",
    }


@pytest.mark.asyncio
@respx.mock
async def test_fedora_skips_neighbor_fallback(client: httpx.AsyncClient) -> None:
    # User asked for country=gb; Fedora had no GB mirrors and substituted
    # neighbors — the comment lists UA/DE/RO, not GB.
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "gb"},
    ).respond(
        200,
        text=(
            "# repo = fedora-41 arch = x86_64 country = UA country = DE country = RO\n"
            "https://de.example.org/fedora/41/os/\n"
        ),
    )
    discoverer = get_discoverer("fedora")
    mirrors = await discoverer.discover(
        client,
        make_host("fedora", codename=None, release_version="41"),
        ("GB",),
    )
    # GB wasn't in the response header → skip to avoid mis-tagging the
    # German mirror as British.
    assert mirrors == []


@pytest.mark.asyncio
@respx.mock
async def test_fedora_unreleased_version_is_a_discovery_error(
    client: httpx.AsyncClient,
) -> None:
    # MirrorManager answers a release it does not know yet with rawhide.
    respx.get("https://mirrors.fedoraproject.org/mirrorlist").respond(
        200,
        text=(
            "# repo = rawhide arch = x86_64 country = US\n"
            "https://us.example.org/fedora/development/rawhide/os/\n"
        ),
    )
    discoverer = get_discoverer("fedora")
    with pytest.raises(DiscoveryError) as excinfo:
        await discoverer.discover(
            client, make_host("fedora", codename=None, release_version="99")
        )
    assert "rawhide" in excinfo.value.reason


@pytest.mark.asyncio
@respx.mock
async def test_fedora_invalid_repo_is_a_discovery_error(
    client: httpx.AsyncClient,
) -> None:
    respx.get("https://mirrors.fedoraproject.org/mirrorlist").respond(
        200,
        text=(
            "# repo = fedora-1 arch = x86_64 error: invalid repo or arch\n"
            "# following repositories are available:\n"
        ),
    )
    discoverer = get_discoverer("fedora")
    with pytest.raises(DiscoveryError):
        await discoverer.discover(
            client, make_host("fedora", codename=None, release_version="1"), ("US",)
        )


@pytest.mark.asyncio
@respx.mock
async def test_fedora_overlay_survives_one_failed_country(
    client: httpx.AsyncClient,
) -> None:
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "us"},
    ).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-41", "arch": "x86_64", "country": "de"},
    ).respond(200, text="# country = de\nhttps://de.example.org/fedora/41/os/\n")
    respx.get(
        url__regex=r"https://mirrors\.fedoraproject\.org/mirrorlist\?.*country=",
    ).respond(200, text="# repo = fedora-41 country = unrelated\n")
    respx.get("https://mirrors.fedoraproject.org/mirrorlist").respond(
        200,
        text=(
            "# repo = fedora-41 arch = x86_64\n"
            "https://us.example.org/fedora/41/os/\n"
            "https://de.example.org/fedora/41/os/\n"
        ),
    )
    discoverer = get_discoverer("fedora")
    mirrors = await discoverer.discover(
        client, make_host("fedora", codename=None, release_version="41")
    )
    assert {m.host: m.country for m in mirrors} == {
        "us.example.org": None,
        "de.example.org": "DE",
    }


@pytest.mark.asyncio
@respx.mock
async def test_arch_status_json(client: httpx.AsyncClient) -> None:
    respx.get("https://archlinux.org/mirrors/status/json/").respond(
        200, text=(FIXTURES / "arch_status.json").read_text()
    )
    discoverer = get_discoverer("arch")
    mirrors = await discoverer.discover(client, make_host("arch", codename=None))
    # Inactive mirrors and rsync:// entries are filtered out.
    assert len(mirrors) == 2
    assert all(m.url.startswith(("http://", "https://")) for m in mirrors)
    assert {m.country for m in mirrors} == {"US", "DE"}


@pytest.mark.asyncio
@respx.mock
async def test_arch_country_filter(client: httpx.AsyncClient) -> None:
    respx.get("https://archlinux.org/mirrors/status/json/").respond(
        200, text=(FIXTURES / "arch_status.json").read_text()
    )
    discoverer = get_discoverer("arch")
    mirrors = await discoverer.discover(
        client, make_host("arch", codename=None), ("US",)
    )
    assert len(mirrors) == 1
    assert mirrors[0].country == "US"


@pytest.mark.asyncio
@respx.mock
async def test_mint_scrapes_repository_table_only(client: httpx.AsyncClient) -> None:
    respx.get("https://www.linuxmint.com/mirrors.php").respond(
        200, text=(FIXTURES / "mint_mirrors.html").read_text()
    )
    discoverer = get_discoverer("mint")
    mirrors = await discoverer.discover(client, make_host("mint", codename="wilma"))
    hosts = {m.host for m in mirrors}
    # Download-mirrors section (ISOs) is ignored.
    assert "iso-only.example.org" not in hosts
    # Repository mirrors are included — both the "World" row (no country) and
    # country-tagged rows.
    assert "fastly.linuxmint.io" in hosts
    assert "mirror.us-a.example.org" in hosts
    assert "mirror.ca-a.example.org" in hosts
    assert "mirror.de-a.example.org" in hosts


@pytest.mark.asyncio
@respx.mock
async def test_mint_country_filter_uses_flag_iso_code(
    client: httpx.AsyncClient,
) -> None:
    respx.get("https://www.linuxmint.com/mirrors.php").respond(
        200, text=(FIXTURES / "mint_mirrors.html").read_text()
    )
    discoverer = get_discoverer("mint")
    mirrors = await discoverer.discover(
        client, make_host("mint", codename="wilma"), ("US",)
    )
    # Filter must pick up US from the flag filename `us.png` and exclude both
    # the "World" row (no country) and other countries.
    assert len(mirrors) == 1
    assert mirrors[0].country == "US"
    assert mirrors[0].host == "mirror.us-a.example.org"


@pytest.mark.asyncio
@respx.mock
async def test_arch_invalid_json_is_a_discovery_error(
    client: httpx.AsyncClient,
) -> None:
    respx.get("https://archlinux.org/mirrors/status/json/").respond(
        200, text="<html>maintenance</html>"
    )
    discoverer = get_discoverer("arch")
    with pytest.raises(DiscoveryError):
        await discoverer.discover(client, make_host("arch", codename=None))


def test_probe_paths_match_distro() -> None:
    arm = "aarch64"
    ubuntu = get_discoverer("ubuntu")
    ubuntu_host = make_host("ubuntu", codename="noble", arch=arm)
    assert ubuntu.probe_path(ubuntu_host) == "dists/noble/InRelease"
    # Archive mirrors carry no ports architectures, whatever the host is.
    assert ubuntu.throughput_path(ubuntu_host) == "dists/noble/Contents-amd64.gz"

    debian = get_discoverer("debian")
    debian_host = make_host("debian", codename="trixie", arch=arm)
    assert debian.probe_path(debian_host) == "dists/trixie/InRelease"
    assert debian.throughput_path(debian_host) == (
        "dists/trixie/main/Contents-arm64.gz"
    )

    mint = get_discoverer("mint")
    mint_host = make_host("mint", codename="zena", arch=arm)
    # Mint publishes Release only, and amd64/i386 only.
    assert mint.probe_path(mint_host) == "dists/zena/Release"
    assert mint.throughput_path(mint_host) == "dists/zena/main/Contents-amd64.gz"

    fedora = get_discoverer("fedora")
    fedora_host = make_host("fedora", codename=None, release_version="45")
    assert fedora.probe_path(fedora_host) == "repodata/repomd.xml"
    assert fedora.throughput_path(fedora_host) == "images/install.img"

    arch = get_discoverer("arch")
    arch_host = make_host("arch", codename=None, arch=arm)
    assert arch.probe_path(arch_host) == "lastsync"
    assert arch.throughput_path(arch_host) == "extra/os/x86_64/extra.db"


def test_codename_defaults_when_host_has_none() -> None:
    assert get_discoverer("mint").probe_path(make_host("mint", codename=None)) == (
        "dists/zena/Release"
    )
    assert get_discoverer("debian").probe_path(make_host("debian", codename=None)) == (
        "dists/trixie/InRelease"
    )


def _listed(url: str) -> Mirror:
    scheme = url.partition("://")[0]
    return Mirror(url=url, host="h.example.org", country="US", protocols=(scheme,))


def test_with_https_candidates() -> None:
    mirrors = [
        _listed("http://a.example.org/pub/"),
        _listed("https://b.example.org/pub/"),
        # Listed under both schemes already: no second https:// entry.
        _listed("http://c.example.org/pub/"),
        _listed("https://c.example.org/pub/"),
    ]
    out = with_https_candidates(mirrors)
    assert [m.url for m in out] == [
        "https://a.example.org/pub/",
        "http://a.example.org/pub/",
        "https://b.example.org/pub/",
        "http://c.example.org/pub/",
        "https://c.example.org/pub/",
    ]
    candidate = out[0]
    assert candidate.protocols == ("https",)
    assert candidate.country == "US"


@pytest.mark.asyncio
@respx.mock
async def test_fedora_http_listing_gains_https_candidate(
    client: httpx.AsyncClient,
) -> None:
    respx.get(
        "https://mirrors.fedoraproject.org/mirrorlist",
        params={"repo": "fedora-45", "arch": "x86_64", "country": "us"},
    ).respond(
        200,
        text=(
            "# repo = fedora-45 arch = x86_64 country = us\n"
            "http://plain.example.org/fedora/45/os/\n"
        ),
    )
    discoverer = get_discoverer("fedora")
    mirrors = await discoverer.discover(
        client, make_host("fedora", codename=None, release_version="45"), ("US",)
    )
    assert [(m.url, m.country) for m in mirrors] == [
        ("https://plain.example.org/fedora/45/os/", "US"),
        ("http://plain.example.org/fedora/45/os/", "US"),
    ]

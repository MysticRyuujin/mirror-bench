"""Per-distro mirror discoverer tests (respx-mocked)."""

from pathlib import Path

import httpx
import pytest
import respx

from mirror_bench.discovery import get_discoverer
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
    assert len(mirrors) == 3
    hosts = {m.host for m in mirrors}
    assert hosts == {
        "mirror.example-a.org",
        "mirror.example-b.org",
        "mirror.example-c.org",
    }
    https_count = sum(1 for m in mirrors if m.is_https)
    assert https_count == 1


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
    assert len(mirrors) == 2


@pytest.mark.asyncio
@respx.mock
async def test_debian_masterlist(client: httpx.AsyncClient) -> None:
    respx.get("https://mirror-master.debian.org/status/Mirrors.masterlist").respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(
        client, make_host("debian", codename="bookworm")
    )
    assert len(mirrors) == 3
    # alpha supports https + http + rsync
    alpha = next(m for m in mirrors if m.host == "mirror.alpha.example.org")
    assert set(alpha.protocols) >= {"https", "http"}
    # gamma is https-only
    gamma = next(m for m in mirrors if m.host == "mirror.gamma.example.org")
    assert gamma.is_https


@pytest.mark.asyncio
@respx.mock
async def test_debian_country_filter(client: httpx.AsyncClient) -> None:
    respx.get("https://mirror-master.debian.org/status/Mirrors.masterlist").respond(
        200, text=(FIXTURES / "debian_masterlist.txt").read_text()
    )
    discoverer = get_discoverer("debian")
    mirrors = await discoverer.discover(
        client, make_host("debian", codename="bookworm"), ("DE",)
    )
    assert len(mirrors) == 1
    assert mirrors[0].country == "DE"


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
async def test_arch_status_json(client: httpx.AsyncClient) -> None:
    respx.get("https://archlinux.org/mirrors/status/json/").respond(
        200, text=(FIXTURES / "arch_status.json").read_text()
    )
    discoverer = get_discoverer("arch")
    mirrors = await discoverer.discover(client, make_host("arch", codename=None))
    # inactive mirrors are filtered out
    assert len(mirrors) == 2
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


def test_probe_paths_match_distro() -> None:
    ubuntu = get_discoverer("ubuntu")
    assert "InRelease" in ubuntu.probe_path(make_host("ubuntu", codename="noble"))
    fedora = get_discoverer("fedora")
    assert "repomd.xml" in fedora.probe_path(make_host("fedora", release_version="41"))
    arch = get_discoverer("arch")
    assert "lastsync" in arch.probe_path(make_host("arch", codename=None))

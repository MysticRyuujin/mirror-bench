"""Opt-in integration tests that hit real mirror infrastructure.

Enable with: MIRROR_BENCH_INTEGRATION=1 uv run pytest -m integration
"""

import math
import os

import pytest

from mirror_bench import distro
from mirror_bench.benchmark import probe, transport
from mirror_bench.discovery import get_discoverer
from tests.conftest import make_host

_ENABLED = os.environ.get("MIRROR_BENCH_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _ENABLED, reason="MIRROR_BENCH_INTEGRATION not set"),
]


@pytest.mark.asyncio
async def test_ubuntu_discovers_real_mirrors() -> None:
    discoverer = get_discoverer("ubuntu")
    async with transport.build_client() as client:
        mirrors = await discoverer.discover(client, make_host("ubuntu"))
    assert len(mirrors) > 10


@pytest.mark.asyncio
async def test_arch_discovers_real_mirrors() -> None:
    discoverer = get_discoverer("arch")
    async with transport.build_client() as client:
        mirrors = await discoverer.discover(client, make_host("arch", codename=None))
    assert len(mirrors) > 50
    assert any(m.is_https for m in mirrors)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["ubuntu", "debian", "fedora", "mint", "arch"])
async def test_default_probe_paths_exist_on_real_mirrors(name: str) -> None:
    """Both probe paths, with default releases, must work on live mirrors.

    This is the check that catches a moved file or an end-of-life default.
    """
    host = distro.from_override(name)
    discoverer = get_discoverer(name)
    async with transport.build_client() as client:
        mirrors = (await discoverer.discover(client, host, ("US",)))[:20]
        assert mirrors, "discovery returned no mirrors"
        latency = await probe.latency_screen(client, mirrors, discoverer, host)
        reachable = [r.mirror for r in latency if r.ok]
        assert reachable, {r.mirror.host: r.error or r.status for r in latency}
        throughput = await probe.throughput_test(client, reachable, discoverer, host)

    usable = [
        r
        for r in throughput.values()
        if r.ok
        and r.bytes_read >= 256 * 1024
        and r.bytes_per_sec is not None
        and math.isfinite(r.bytes_per_sec)
        and r.bytes_per_sec > 0
    ]
    # Most reachable mirrors must serve the throughput file, or the file is
    # a poor choice for ranking.
    assert len(usable) >= 0.8 * len(reachable), {
        r.mirror.host: r.error or r.status for r in throughput.values()
    }

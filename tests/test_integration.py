"""Opt-in integration tests that hit real mirror infrastructure.

Enable with: MIRROR_BENCH_INTEGRATION=1 uv run pytest -m integration
"""

import os

import pytest

from mirror_bench.benchmark import transport
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

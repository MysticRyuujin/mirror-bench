"""Shared pytest fixtures."""

from typing import TYPE_CHECKING

import httpx
import pytest_asyncio

from mirror_bench.models import HostInfo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        yield c


def make_host(
    distro_id: str = "ubuntu",
    codename: str | None = "noble",
    release_version: str | None = None,
    arch: str = "x86_64",
) -> HostInfo:
    return HostInfo(
        distro_id=distro_id,
        base_distro_id=distro_id,
        codename=codename,
        release_version=release_version,
        arch=arch,
    )

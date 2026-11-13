"""Shared httpx.AsyncClient factory."""

import ssl

import httpx

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=5.0, write=3.0, pool=5.0)
_MAX_REDIRECTS = 3
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

USER_AGENT = "mirror-bench/0.1.0 (+https://github.com/MysticRyuujin/mirror-bench)"


def build_client(
    *,
    tls13_only: bool = False,
    verify: bool = True,
    timeout: httpx.Timeout | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Build the shared AsyncClient for discovery + probing.

    Redirects are followed for probes too: a package manager pays for the extra
    hop on each request, so the hop belongs in the measurement.
    """
    ctx: ssl.SSLContext | bool
    if verify:
        ctx = ssl.create_default_context()
        if tls13_only:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    else:
        ctx = False
    return httpx.AsyncClient(
        http2=True,
        timeout=timeout or _DEFAULT_TIMEOUT,
        limits=_DEFAULT_LIMITS,
        follow_redirects=follow_redirects,
        max_redirects=_MAX_REDIRECTS,
        verify=ctx,
        headers={"User-Agent": USER_AGENT},
    )

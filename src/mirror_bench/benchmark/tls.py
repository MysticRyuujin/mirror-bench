"""TLS version + certificate inspection helpers."""

import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def inspect(response: httpx.Response) -> tuple[str | None, bool | None]:
    """Return (tls_version, cert_valid) for a completed HTTP response.

    Returns (None, None) for plain HTTP. When we can reach the underlying SSLObject via
    httpx's `network_stream` extension, we report its negotiated version; cert_valid is
    True because successful response delivery with a verifying transport implies chain
    + hostname + expiry all passed.
    """
    if response.url.scheme != "https":
        return (None, None)

    network_stream = response.extensions.get("network_stream")
    if network_stream is None:
        return (None, None)

    get_extra = getattr(network_stream, "get_extra_info", None)
    if not callable(get_extra):
        return (None, None)

    ssl_object = get_extra("ssl_object")
    if not isinstance(ssl_object, ssl.SSLObject):
        return (None, None)

    return (ssl_object.version(), True)

"""HTTP/3 discovery tests."""

import pytest

from mirror_bench.benchmark import h3


@pytest.mark.parametrize(
    ("header", "port"),
    [
        (None, None),
        ("", None),
        ('h3=":443"; ma=3600', 443),
        # Fastly: no space after the separators, draft ids after the final one.
        ('h3=":443";ma=86400,h3-29=":443";ma=86400,h3-27=":443";ma=86400', 443),
        ('h3-29=":443"; ma=86400', None),
        ('h2=":443"; ma=60, h3=":8443"; ma=60', 8443),
        ('H3=":443"', 443),
        ("clear", None),
        # An alternative on another host is not the measured mirror.
        ('h3="alt.example.org:443"; ma=60', None),
        ('h3="alt.example.org:443", h3=":4433"', 4433),
        ('h3=":https"', None),
        ("h3", None),
        ('h3=":0"', None),
        ('h3=":65536"', None),
        ('h3=":' + "9" * 5000 + '"', None),
    ],
)
def test_parse_alt_svc(header: str | None, port: int | None) -> None:
    assert h3.parse_alt_svc(header) == port

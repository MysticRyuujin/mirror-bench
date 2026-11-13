"""HTTP/3 support: discovery from the Alt-Svc response header (RFC 7838)."""


def parse_alt_svc(header: str | None) -> int | None:
    """Return the port where the responding origin offers HTTP/3, or None.

    Only the final `h3` protocol id counts; draft ids such as `h3-29` are
    obsolete. An alternative on another host is skipped: it is a different
    endpoint from the mirror that was measured.
    """
    if not header:
        return None
    for entry in header.split(","):
        alternative = entry.split(";", 1)[0].strip()
        if alternative.lower() == "clear":
            return None
        protocol, sep, authority = alternative.partition("=")
        if not sep or protocol.strip().lower() != "h3":
            continue
        alt_host, _, port = authority.strip().strip('"').rpartition(":")
        # The length check also keeps int() away from absurd digit strings,
        # which raise instead of returning a number.
        if alt_host or not port.isascii() or not port.isdigit() or len(port) > 5:
            continue
        if 0 < int(port) <= 65535:
            return int(port)
    return None

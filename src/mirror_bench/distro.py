"""Host distribution auto-detection."""

import platform
from dataclasses import replace

from mirror_bench.models import HostInfo

# Distros whose mirror layout is keyed by Debian-style codename (noble, bookworm, …)
# rather than a numeric release. Used to decide how to interpret --release.
_CODENAME_DISTROS: frozenset[str] = frozenset({"ubuntu", "debian", "mint"})

SUPPORTED: frozenset[str] = frozenset({"ubuntu", "debian", "fedora", "mint", "arch"})

_ALIASES: dict[str, str] = {
    "ubuntu": "ubuntu",
    "debian": "debian",
    "fedora": "fedora",
    "linuxmint": "mint",
    "mint": "mint",
    "arch": "arch",
    "archlinux": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "pop": "ubuntu",
    "elementary": "ubuntu",
    "zorin": "ubuntu",
    "neon": "ubuntu",
    "kali": "debian",
    "parrot": "debian",
    "devuan": "debian",
    "raspbian": "debian",
    "rocky": "fedora",
    "almalinux": "fedora",
    "centos": "fedora",
    "rhel": "fedora",
    "nobara": "fedora",
    "ol": "fedora",
}

_CODENAME_FALLBACKS: dict[tuple[str, str], str] = {
    ("ubuntu", "24.04"): "noble",
    ("ubuntu", "22.04"): "jammy",
    ("ubuntu", "20.04"): "focal",
    ("debian", "12"): "bookworm",
    ("debian", "13"): "trixie",
    ("debian", "11"): "bullseye",
}


class DistroDetectionError(RuntimeError):
    """Base class for distro resolution failures. Callers format for display."""


class UnsupportedDistroError(DistroDetectionError):
    """Caller requested (or system reports) a distro outside the supported set."""

    def __init__(self, distro: str, *, source: str = "--distro") -> None:
        self.distro = distro
        self.source = source
        self.supported: tuple[str, ...] = tuple(sorted(SUPPORTED))
        super().__init__(
            f"unsupported {source} {distro!r}; supported: {list(self.supported)}"
        )


class OSReleaseMissingError(DistroDetectionError):
    """Auto-detection attempted but /etc/os-release was not readable."""

    def __init__(self) -> None:
        super().__init__(
            "could not auto-detect distribution (no /etc/os-release); pass --distro"
        )


def detect() -> HostInfo | None:
    """Read /etc/os-release and return a HostInfo, or None when unreadable."""
    try:
        info = platform.freedesktop_os_release()
    except OSError:
        return None
    return _host_info_from_os_release(info)


def from_override(distro: str, release: str | None = None) -> HostInfo:
    """Build a HostInfo from an explicit --distro (+ optional --release).

    `release` is interpreted per-distro:
      - ubuntu / debian / mint -> codename (noble, bookworm, wilma, …)
      - fedora -> numeric release (41, 42, …)
      - arch -> ignored (Arch is rolling; paths don't use a release key)
    """
    base = _ALIASES.get(distro.lower())
    if base is None or base not in SUPPORTED:
        raise UnsupportedDistroError(distro)
    codename: str | None
    release_version: str | None
    if base in _CODENAME_DISTROS:
        codename = release or _default_codename(base)
        release_version = None
    elif base == "fedora":
        codename = None
        release_version = release  # discoverer defaults to current stable if None
    else:  # arch: no release concept
        codename = None
        release_version = None
    return HostInfo(
        distro_id=distro.lower(),
        base_distro_id=base,
        codename=codename,
        release_version=release_version,
        arch=_normalized_arch(),
    )


def resolve(
    distro_override: str | None,
    release_override: str | None = None,
) -> HostInfo:
    """Pick a HostInfo: explicit overrides win, else auto-detect, else raise."""
    if distro_override:
        return from_override(distro_override, release=release_override)
    detected = detect()
    if detected is None:
        raise OSReleaseMissingError
    if detected.base_distro_id not in SUPPORTED:
        raise UnsupportedDistroError(detected.distro_id, source="auto-detected distro")
    if release_override is not None:
        # Let --release shadow the auto-detected value for the matching slot.
        if detected.base_distro_id in _CODENAME_DISTROS:
            detected = replace(detected, codename=release_override)
        elif detected.base_distro_id == "fedora":
            detected = replace(detected, release_version=release_override)
    return detected


def _host_info_from_os_release(info: dict[str, str]) -> HostInfo:
    distro_id = info.get("ID", "").lower()
    id_like = [x.lower() for x in info.get("ID_LIKE", "").split()]
    base = _ALIASES.get(distro_id)
    if base is None:
        for candidate in id_like:
            base = _ALIASES.get(candidate)
            if base is not None:
                break
    codename = info.get("VERSION_CODENAME") or None
    version = info.get("VERSION_ID") or None
    if not codename and base and version:
        codename = _CODENAME_FALLBACKS.get((base, version))
    return HostInfo(
        distro_id=distro_id or (base or "unknown"),
        base_distro_id=base or distro_id or "unknown",
        codename=codename,
        release_version=version,
        arch=_normalized_arch(),
    )


def _normalized_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


def _default_codename(base: str) -> str | None:
    # Reasonable defaults when the user passes --distro without --codename.
    return {
        "ubuntu": "noble",
        "debian": "bookworm",
        "mint": "noble",
    }.get(base)

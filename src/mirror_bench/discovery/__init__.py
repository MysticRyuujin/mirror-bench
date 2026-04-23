"""Per-distribution mirror discoverers."""

from mirror_bench.discovery.arch import ArchDiscoverer
from mirror_bench.discovery.base import MirrorDiscoverer
from mirror_bench.discovery.debian import DebianDiscoverer
from mirror_bench.discovery.fedora import FedoraDiscoverer
from mirror_bench.discovery.mint import MintDiscoverer
from mirror_bench.discovery.ubuntu import UbuntuDiscoverer

DISCOVERERS: dict[str, type[MirrorDiscoverer]] = {
    "ubuntu": UbuntuDiscoverer,
    "debian": DebianDiscoverer,
    "fedora": FedoraDiscoverer,
    "mint": MintDiscoverer,
    "arch": ArchDiscoverer,
}


class UnknownDiscovererError(KeyError):
    """Raised when a distro id has no registered discoverer."""

    def __init__(self, distro: str) -> None:
        self.distro = distro
        self.supported: tuple[str, ...] = tuple(sorted(DISCOVERERS))
        super().__init__(
            f"no discoverer for distro {distro!r}; supported: {list(self.supported)}"
        )


def get_discoverer(base_distro_id: str) -> MirrorDiscoverer:
    try:
        cls = DISCOVERERS[base_distro_id]
    except KeyError as exc:
        raise UnknownDiscovererError(base_distro_id) from exc
    return cls()


__all__ = [
    "DISCOVERERS",
    "MirrorDiscoverer",
    "UnknownDiscovererError",
    "get_discoverer",
]

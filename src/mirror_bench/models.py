"""Core data models."""

from dataclasses import dataclass, field, replace


@dataclass(slots=True, frozen=True)
class HostInfo:
    """Information about the host or the target distribution being benchmarked."""

    distro_id: str
    base_distro_id: str
    codename: str | None
    release_version: str | None
    arch: str

    @property
    def apt_arch(self) -> str:
        """Architecture name as used in apt paths (x86_64 -> amd64)."""
        return _APT_ARCH.get(self.arch, self.arch)


_APT_ARCH: dict[str, str] = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "i686": "i386",
}


@dataclass(slots=True, frozen=True)
class Mirror:
    """A discovered mirror endpoint."""

    url: str
    host: str
    country: str | None
    protocols: tuple[str, ...] = ()

    @property
    def is_https(self) -> bool:
        return self.url.startswith("https://")


@dataclass(slots=True, frozen=True)
class ProbeResult:
    """Outcome of a single HTTP probe against a mirror."""

    mirror: Mirror
    ttfb_ms: float | None
    total_ms: float | None
    bytes_read: int
    bytes_per_sec: float | None
    status: int | None
    http_version: str | None
    tls_version: str | None
    cert_valid: bool | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None and self.status is not None and 200 <= self.status < 400
        )


@dataclass(slots=True, frozen=True)
class Score:
    """Composite ranking for a mirror."""

    mirror: Mirror
    latency_ms: float | None
    throughput_bps: float | None
    security_score: float
    composite: float
    probe: ProbeResult
    throughput_probe: ProbeResult | None = None


@dataclass(slots=True, frozen=True)
class Weights:
    """User-overridable scoring weights."""

    latency: float = 0.4
    throughput: float = 0.4
    security: float = 0.2

    def normalized(self) -> Weights:
        total = self.latency + self.throughput + self.security
        if total <= 0:
            return Weights()
        return replace(
            self,
            latency=self.latency / total,
            throughput=self.throughput / total,
            security=self.security / total,
        )


@dataclass(slots=True, frozen=True)
class BenchConfig:
    """Runtime configuration for a benchmark run."""

    distro: str | None = None
    countries: tuple[str, ...] = ()
    top: int = 15
    concurrency: int = 20
    https_only: bool = False
    tls13_only: bool = False
    weights: Weights = field(default_factory=Weights)
    samples: int = 3
    skip_throughput: bool = False

# mirror-bench

[![CI](https://github.com/MysticRyuujin/mirror-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/MysticRyuujin/mirror-bench/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/linux-mirror-bench.svg)](https://pypi.org/project/linux-mirror-bench/)
[![Python](https://img.shields.io/pypi/pyversions/linux-mirror-bench.svg)](https://pypi.org/project/linux-mirror-bench/)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Container](https://img.shields.io/badge/ghcr.io-MysticRyuujin%2Fmirror--bench-2ea44f?logo=docker)](https://github.com/MysticRyuujin/mirror-bench/pkgs/container/mirror-bench)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

A cross-distribution Linux package mirror benchmarking tool.

Ranks mirrors by **latency**, **throughput**, and **security** (HTTPS / TLS 1.3 / cert validity / HTTP/2).

`mirror-bench` is **read-only**: it discovers mirrors, probes them, prints a
ranked table, and exits. It never touches `/etc/apt/sources.list`,
`/etc/yum.repos.d/`, pacman's `mirrorlist`, or any other system configuration.

- Cross-distro: **Ubuntu, Debian, Fedora, Linux Mint, Arch**.
- Modern Python: 3.14, strict typing, async I/O (`httpx` + `asyncio.TaskGroup`).
- Shippable everywhere: `pipx`, `uv tool`, PyPI wheels, and a minimal
  multi-arch container on GHCR.

## Table of contents

- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Running in Docker](#running-in-docker)
- [Shell completion](#shell-completion)
- [How it works](#how-it-works)
- [Development](#development)
- [Security](#security)
- [License](#license)

## Quick start

Options go after the subcommand (typer / git / kubectl convention).

```sh
# Auto-detect distro, benchmark top 15 mirrors
mirror-bench bench

# List discovered mirrors without benchmarking
mirror-bench list

# Benchmark Ubuntu mirrors from the US and Canada
mirror-bench bench --distro ubuntu --country US,CA

# Only consider mirrors that serve HTTPS with TLS 1.3
mirror-bench bench --https-only --tls13-only

# Adjust scoring weights (auto-normalized)
mirror-bench bench --weights lat=0.6,thr=0.3,sec=0.1

# Machine-readable output for scripts
mirror-bench bench --json | jq '.results[0]'
mirror-bench bench --csv > mirrors.csv
```

## Installation

The PyPI distribution is **`linux-mirror-bench`** (the short `mirror-bench`
name was too similar to an existing project). The installed CLI is still
`mirror-bench`.

### With `uv` (recommended)

```sh
uv tool install linux-mirror-bench
mirror-bench --help
```

### With `pipx`

```sh
pipx install linux-mirror-bench
mirror-bench --help
```

### One-shot via `uvx`

```sh
uvx --from linux-mirror-bench mirror-bench bench --distro fedora
```

### From source

```sh
git clone https://github.com/MysticRyuujin/mirror-bench
cd mirror-bench
uv sync
uv run mirror-bench bench
```

## Usage

### Subcommands

| Command              | What it does                                                     |
| -------------------- | ---------------------------------------------------------------- |
| `mirror-bench bench` | Discover, probe (two-phase), and print a ranked table. (default) |
| `mirror-bench list`  | Discover only. Print the mirror roster as a table.               |

Running `mirror-bench` with no subcommand is equivalent to `mirror-bench bench`.

### Common flags

| Flag                          | Description                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| `--distro, -d NAME`           | One of `ubuntu`, `debian`, `fedora`, `mint`, `arch`.                                        |
| `--release, -r VALUE`         | Release override: codename for apt (noble, bookworm, wilma) or numeric for Fedora (41, 42). |
| `--country, -c US,CA,GB`      | ISO 3166-1 alpha-2 country codes to filter on.                                              |
| `--top, -n N`                 | How many mirrors to include in phase 2 / display (default 15).                              |
| `--concurrency N`             | Max parallel HTTP probes (default 20).                                                      |
| `--https-only`                | Hard-exclude mirrors without HTTPS.                                                         |
| `--tls13-only`                | Hard-exclude mirrors that don't negotiate TLS 1.3.                                          |
| `--weights lat=…,thr=…,sec=…` | Override scoring weights (auto-normalized).                                                 |
| `--no-throughput`             | Skip phase 2. Phase-1 latency screen only.                                                  |
| `--json`                      | Emit JSON to stdout. Suppresses the table + progress.                                       |
| `--csv`                       | Emit CSV to stdout. Suppresses the table + progress.                                        |

## Running in Docker

A minimal multi-arch (linux/amd64 + linux/arm64) image is published to GHCR:

```sh
docker pull ghcr.io/mysticryuujin/mirror-bench:latest
```

The image is built on `python:3.14-slim-bookworm`, runs as a non-root user
(`uid 65532`), and ships only the wheel + runtime deps (no uv, no sources,
no build chain). `ENTRYPOINT` is `mirror-bench`, so you can pass CLI args
directly.

> The image renders a colored, properly-widened table even without `-it`.
> If you want **rich to use your host terminal's exact width** (and react to
> resizes), add `-it`; otherwise the image falls back to a sensible 120-col
> table. Set `NO_COLOR=1` if you'd rather have plain text — e.g. when
> redirecting to a file.

### Basic invocation

```sh
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest --help
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest bench --distro ubuntu --country US
```

### Per-distribution examples

Pick a `--distro` — the image is the same for all of them.

```sh
# Ubuntu — default per-country sweep if no --country provided
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro ubuntu --country US,CA --top 10

# Debian
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro debian --country DE,FR --https-only

# Fedora — release version inferred from defaults if not passed via --distro value
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro fedora --tls13-only --top 10

# Linux Mint
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro mint --top 15

# Arch Linux
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro arch --country DE,NL,SE
```

### Machine-readable output

```sh
docker run --rm ghcr.io/mysticryuujin/mirror-bench:latest \
  bench --distro arch --json | jq '.results[] | {host: .mirror.host, latency_ms, score: .composite}'
```

### Running with auto-detection inside distro base images

If you'd rather let `mirror-bench` auto-detect the host distribution (useful
when testing from inside a specific distro's container), use
[`uv`](https://docs.astral.sh/uv/) — it bootstraps its own Python 3.14
regardless of what the distro ships. Distro-package-manager installs of
`python3.14` don't work on current stable Ubuntu/Debian/Fedora (they ship
older Python).

```sh
# Inside an Ubuntu container — distro auto-detected from /etc/os-release
docker run --rm --entrypoint bash ubuntu:24.04 -c \
  "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null && \
   curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null && \
   ~/.local/bin/uvx --from linux-mirror-bench mirror-bench bench"

# Inside a Debian container
docker run --rm --entrypoint bash debian:bookworm -c \
  "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null && \
   curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null && \
   ~/.local/bin/uvx --from linux-mirror-bench mirror-bench bench"

# Inside a Fedora container
docker run --rm --entrypoint bash fedora:41 -c \
  "dnf install -y -q curl ca-certificates >/dev/null && \
   curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null && \
   ~/.local/bin/uvx --from linux-mirror-bench mirror-bench bench"

# Inside an Arch container
docker run --rm --entrypoint bash archlinux:latest -c \
  "pacman -Sy --noconfirm --needed curl ca-certificates >/dev/null && \
   curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null && \
   ~/.local/bin/uvx --from linux-mirror-bench mirror-bench bench"
```

For most uses the `ghcr.io/mysticryuujin/mirror-bench` image is simpler — it already
has the CLI and lets you benchmark _any_ distro via `--distro`.

### Building the image yourself

The `Dockerfile` is a two-stage build:

1. **Builder** — `python:3.14-slim-bookworm` + the pinned `uv` from
   `ghcr.io/astral-sh/uv`. Generates the wheel, then installs it into a
   self-contained virtualenv at `/opt/venv`.
2. **Runtime** — fresh `python:3.14-slim-bookworm`, copies only `/opt/venv`
   from the builder, refreshes the CA bundle, creates a non-root user (`uid
65532`), and sets `mirror-bench` as the `ENTRYPOINT`.

No dev dependencies, source code, or uv binary lands in the final image.

#### Standard local build

```sh
git clone https://github.com/MysticRyuujin/mirror-bench && cd mirror-bench

# Shortest path — Makefile shortcut tags as `mirror-bench:dev`.
make docker-build
docker run --rm mirror-bench:dev bench --distro arch --top 5

# Or run `docker build` directly for full control over tags and args.
docker build -t mirror-bench:local .
docker run --rm mirror-bench:local --help
```

#### Build args

All arguments are optional; defaults match what CI ships.

| Arg              | Default  | Purpose                                                             |
| ---------------- | -------- | ------------------------------------------------------------------- |
| `PYTHON_VERSION` | `3.14`   | Base image tag (`python:<PYTHON_VERSION>-slim-bookworm`).           |
| `UV_VERSION`     | `0.11.7` | uv release pulled from `ghcr.io/astral-sh/uv:<UV_VERSION>`.         |
| `VERSION`        | `0.1.0`  | Value embedded in the `org.opencontainers.image.version` OCI label. |

Example:

```sh
docker build \
  --build-arg VERSION="$(uv version --short)" \
  --build-arg PYTHON_VERSION=3.14 \
  --build-arg UV_VERSION=0.11.7 \
  -t mirror-bench:"$(uv version --short)" \
  -t mirror-bench:latest \
  .
```

#### Multi-arch (amd64 + arm64) build via buildx

The released image on GHCR is built for both architectures. To produce the
same locally (useful for testing on Apple Silicon before publishing):

```sh
docker buildx create --name mb --use --bootstrap  # one-time
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg VERSION="$(uv version --short)" \
  -t mirror-bench:multiarch \
  --load .     # or --push for a registry
```

`--load` only supports a single platform; use `--push` (against a registry
you control) to actually materialize a multi-arch manifest.

#### Inspecting the result

```sh
docker image inspect mirror-bench:local \
  --format '{{json .Config.Labels}}' | jq      # OCI labels
docker image ls mirror-bench:local              # size (~170 MB)
docker run --rm mirror-bench:local list --distro arch --json | jq '.mirrors | length'
```

#### Makefile shortcuts

```sh
make docker-build   # docker build -t mirror-bench:dev .
make docker-test    # build + run --help + `list --distro arch --json` smoke test
```

## Shell completion

`mirror-bench` ships completion scripts for **bash**, **zsh**, and **fish**.
Two paths, depending on whether shell auto-detection works in your environment:

### Recommended: the `completion` subcommand (no auto-detect)

Always works, including in containers, CI, and sandboxed shells:

```sh
# bash
mirror-bench completion bash > ~/.local/share/bash-completion/completions/mirror-bench

# zsh — make sure `~/.zfunc` is on your fpath
mirror-bench completion zsh > ~/.zfunc/_mirror-bench

# fish
mirror-bench completion fish > ~/.config/fish/completions/mirror-bench.fish
```

Restart your shell (or `source` the file) and completion is live.

### Auto-install via typer (when run in a real terminal)

```sh
mirror-bench --install-completion   # typer detects the shell and installs
mirror-bench --show-completion      # prints the script for the detected shell
```

This relies on [shellingham](https://github.com/sarugaku/shellingham) to
detect your shell from the parent process. It works in normal interactive
shells but can fail inside `uv run`, nested sandboxes, or minimal containers —
use the `completion` subcommand in those cases.

### After install

Tab-complete subcommands, options, and their values:

```text
$ mirror-bench <TAB>
bench  list  completion
$ mirror-bench bench --<TAB>
--distro  --country  --top  --concurrency  --https-only  --tls13-only  …
```

## How it works

1. **Discover** — fetch the canonical mirror list for the target distribution:
   - Ubuntu: `mirrors.ubuntu.com/<CC>.txt` swept across a default country
     set (`mirrors.ubuntu.com/mirrors.txt` returns a geo-selected _single_
     mirror, not a full list — so we don't rely on it alone).
   - Debian: `mirror-master.debian.org/status/Mirrors.masterlist` (RFC822
     multi-record format).
   - Fedora: `mirrors.fedoraproject.org/mirrorlist?repo=&arch=&country=`.
   - Linux Mint: scraped from `linuxmint.com/mirrors.php`.
   - Arch: `archlinux.org/mirrors/status/json/` (JSON, filtered to active).
2. **Phase 1 — latency screen.** Concurrent ranged GET (`bytes=0-1023`) on the
   distro's canonical small metadata file (`InRelease`, `repomd.xml`,
   `lastsync`). Three samples per mirror, **median TTFB** used for ranking.
3. **Phase 2 — throughput test.** Full streaming GET of a representative file
   (`Contents-<arch>.gz` for apt, `core.db` for Arch, etc.) on the top N from
   phase 1, capped at 5 MiB. `bytes_per_sec` is measured from first-byte to
   end-of-stream so steady-state bandwidth isn't polluted by connect/TLS
   overhead.
4. **Score.** Weighted composite of normalized latency (inverse), throughput,
   and security (HTTPS + TLS 1.3 + cert-valid + HTTP/2, max 3.5). Weights
   default to `lat=0.4, thr=0.4, sec=0.2` and are user-overridable.
5. **Render.** A `rich.Table`, or JSON / CSV for scripting.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full dev loop.

```sh
make install       # uv sync --all-extras
make hooks         # install pre-commit + commit-msg hooks
make ci-local      # lint + typecheck + tests + security + docker-test
```

Integration tests (opt-in, real network):

```sh
MIRROR_BENCH_INTEGRATION=1 uv run pytest -m integration
```

## Security

Vulnerability reports — see [`SECURITY.md`](SECURITY.md) for the private
disclosure process. **Please do not open public issues for security problems.**

Supply-chain guarantees (starting at 0.1.0):

- Releases published via GitHub Actions OIDC Trusted Publishing to PyPI — no
  long-lived tokens.
- Wheels and container images carry **SLSA build provenance** attestations.
- Container image published to `ghcr.io/mysticryuujin/mirror-bench` with SBOM
  generated at build.
- `uv.lock` pins dependency graph; Dependabot monitors it weekly.

## License

[GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).

The AGPL requires that anyone who runs a modified version of `mirror-bench`
accessible over a network (for example, as part of a hosted service) must make
the modified source available to the users of that service. If you are
embedding or redistributing `mirror-bench`, read the [license text](LICENSE)
for the full terms.

# Contributing to mirror-bench

Thanks for wanting to contribute! This document covers the dev loop and the few
conventions we care about.

## Prerequisites

- Python **3.14** (via `pyenv`, `asdf`, `mise`, or `uv python install 3.14`).
- [`uv`](https://docs.astral.sh/uv/) 0.11+.
- Docker (only needed if you touch the `Dockerfile` or `ci-local`).

## One-time setup

```sh
git clone https://github.com/MysticRyuujin/mirror-bench
cd mirror-bench
make install          # uv sync --all-extras
make hooks            # installs pre-commit + commit-msg hook
```

## The dev loop

```sh
make fmt              # ruff format
make lint             # ruff check
make typecheck        # mypy --strict on src/
make test             # pytest (unit)
make test-integration # pytest -m integration (real network)
make security         # bandit + pip-audit
make ci-local         # everything CI runs, locally
```

Alternatively without Make:

```sh
uv run pytest
uv run ruff check .
uv run mypy src
```

## Commit style

We follow [Conventional Commits](https://www.conventionalcommits.org/). The
`commitizen` pre-commit hook enforces this on `commit-msg`. Short reference:

- `feat: add fedora throughput probe`
- `fix(discovery): handle empty arch mirror list`
- `docs: clarify --tls13-only filter`
- `chore(ci): bump setup-uv to v7`
- `refactor!: drop --mirrors-txt-fallback` (breaking change)

First-time users may find `uv run --with commitizen cz commit` helpful — it
walks you through the format interactively.

## Branching + PRs

- Work on a feature branch; don't push directly to `main` (the
  `no-commit-to-branch` hook enforces this locally).
- Keep PRs focused. Mixed refactors + features are harder to review.
- If your change alters behavior, update `CHANGELOG.md` under `## [Unreleased]`.
- All CI jobs must pass before merge (`lint`, `typecheck`, `test`, `security`,
  `docker`).

## Adding a new distribution

1. Create `src/mirror_bench/discovery/<name>.py` implementing
   `MirrorDiscoverer` (`discover`, `probe_path`, `throughput_path`).
2. Register it in `src/mirror_bench/discovery/__init__.py`'s `DISCOVERERS` map.
3. Add the distro's `ID` / `ID_LIKE` aliases to
   `src/mirror_bench/distro.py::_ALIASES`.
4. Add a respx-mocked test with a realistic fixture under
   `tests/fixtures/<name>_*`.
5. Update `README.md` supported distributions.

## Release process (maintainers)

1. Land all PRs for the release.
2. Bump version via commitizen:
   `uv run --with commitizen cz bump --check-consistency`.
3. Push tag: `git push origin main --tags`.
4. The `Release` workflow builds wheel + multi-arch container, publishes to
   PyPI via OIDC trusted publishing, pushes to `ghcr.io`, attaches SLSA
   provenance, and creates a GitHub Release.

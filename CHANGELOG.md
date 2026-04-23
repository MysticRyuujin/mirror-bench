# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2](https://github.com/MysticRyuujin/mirror-bench/compare/v0.1.1...v0.1.2) (2026-04-23)


### Bug Fixes

* **docs:** lowercase ghcr.io references (docker pull requires lowercase) ([#8](https://github.com/MysticRyuujin/mirror-bench/issues/8)) ([31fcf57](https://github.com/MysticRyuujin/mirror-bench/commit/31fcf57239fc98eecb6df9fe8fed06400cb55dc7))


### Documentation

* add shields.io badges at top of README ([#6](https://github.com/MysticRyuujin/mirror-bench/issues/6)) ([c25c12b](https://github.com/MysticRyuujin/mirror-bench/commit/c25c12bdc36aa6af67cbbb1b8b7ec65c000d7a53))

## [0.1.1](https://github.com/MysticRyuujin/mirror-bench/compare/v0.1.0...v0.1.1) (2026-04-23)


### Bug Fixes

* **ci:** pin aquasecurity/trivy-action to a version that exists ([#2](https://github.com/MysticRyuujin/mirror-bench/issues/2)) ([9984cd0](https://github.com/MysticRyuujin/mirror-bench/commit/9984cd018aaaa6de34b5cdf8261752f563187858))


### Dependencies

* **actions:** bump the actions group across 1 directory with 11 updates ([#4](https://github.com/MysticRyuujin/mirror-bench/issues/4)) ([4aba2a6](https://github.com/MysticRyuujin/mirror-bench/commit/4aba2a68079d2029bf5cc387d9a6eae459d9ff2a))

## [Unreleased]

## [0.1.0] - 2026-04-23

### Added

- Cross-distribution mirror benchmarking for **Ubuntu, Debian, Fedora,
  Linux Mint, and Arch**.
- Two-phase probe: async latency screen (ranged GET on each distro's canonical
  metadata file; median of 3 samples) followed by a throughput test on the
  top-N candidates.
- Weighted composite scoring across latency, throughput, and security (HTTPS +
  TLS 1.3 + valid cert + HTTP/2). Weights adjustable via
  `--weights lat=…,thr=…,sec=…`.
- `bench` and `list` subcommands with `--json` / `--csv` / `--https-only` /
  `--tls13-only` / `--no-throughput` / `--country` / `--top` / `--concurrency`.
- Host auto-detection via `/etc/os-release`, with derivative alias support
  (Pop!\_OS, Kali, Rocky, etc.). `--distro` override for containers and macOS.
- Shell completion via typer (`--install-completion` / `--show-completion`).
- Multi-stage Dockerfile (`python:3.14-slim-bookworm`, non-root uid 65532).
- GitHub Actions CI + release pipelines with OIDC PyPI publishing, multi-arch
  container image, SLSA build provenance, and Trivy image scanning.
- Pre-commit hooks: ruff, mypy, bandit, gitleaks, hadolint, shellcheck,
  yamllint, markdownlint, commitizen.
- `SECURITY.md` with responsible-disclosure workflow and supply-chain notes.
- Licensed under **GNU AGPL-3.0-or-later** — users of hosted/network-facing
  modified versions must receive the modified source.

[Unreleased]: https://github.com/MysticRyuujin/mirror-bench/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MysticRyuujin/mirror-bench/releases/tag/v0.1.0

# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

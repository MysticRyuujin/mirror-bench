# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0](https://github.com/MysticRyuujin/mirror-bench/compare/v0.2.0...v0.3.0) (2026-11-13)


### Features

* measure mirror freshness and drop stale mirrors ([#18](https://github.com/MysticRyuujin/mirror-bench/issues/18)) ([462ac42](https://github.com/MysticRyuujin/mirror-bench/commit/462ac42017f1026c6892701aaa0452b791a0c498))


### Bug Fixes

* make completion work without click, and reject error pages as probes ([#19](https://github.com/MysticRyuujin/mirror-bench/issues/19)) ([0c2427d](https://github.com/MysticRyuujin/mirror-bench/commit/0c2427dcb949f394e0118a386407d215d732465b))
* try https for mirrors listed as http, and write plain output with no TTY ([#17](https://github.com/MysticRyuujin/mirror-bench/issues/17)) ([07d38ee](https://github.com/MysticRyuujin/mirror-bench/commit/07d38eec00a0c5669a728723a13a9d805f6113c8))


### Dependencies

* **actions:** match action versions in integration.yml ([#15](https://github.com/MysticRyuujin/mirror-bench/issues/15)) ([35da73d](https://github.com/MysticRyuujin/mirror-bench/commit/35da73d052acf4f1ea67c2f14f4df0b09a8b8c98))

## [0.2.0](https://github.com/MysticRyuujin/mirror-bench/compare/v0.1.2...v0.2.0) (2026-11-13)


### ⚠ BREAKING CHANGES

* follow redirects in probes and require a 2xx response; reject an https mirror that redirects to http
* report throughput from phase 2 only; throughput_bps is null when phase 2 fails or is skipped
* remove the certificate point from the security score; the maximum is 2.5
* change default releases to Debian trixie, Mint zena, and Fedora 45
* reject --json together with --csv
* stop mapping distros with their own mirror network (rocky, almalinux, centos, rhel, ol, manjaro, kali, parrot, devuan, raspbian) to another distro

### Features

* add --http3 to confirm HTTP/3 with a QUIC probe (optional http3 extra) ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* add throughput_error to JSON and CSV output ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* report mirrors that advertise HTTP/3 (HTTP/3 column, h3_advertised) ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))


### Bug Fixes

* add a time limit to both probe phases ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* change default releases to Debian trixie, Mint zena, and Fedora 45 ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* correct probe and throughput paths for Ubuntu, Mint, Arch, and Fedora ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* **docker:** remove pip from the runtime image ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* drop rsync entries from Arch discovery ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* exit with code 1 and a message when discovery fails ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* follow redirects in probes and require a 2xx response; reject an https mirror that redirects to http ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* handle Debian records with no Country, and try https and http for each Debian site ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* reject --concurrency 0 and --top 0 ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* reject --json together with --csv ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* remove the certificate point from the security score; the maximum is 2.5 ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* report throughput from phase 2 only; throughput_bps is null when phase 2 fails or is skipped ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* run bench when no subcommand is given ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* stop mapping distros with their own mirror network (rocky, almalinux, centos, rhel, ol, manjaro, kali, parrot, devuan, raspbian) to another distro ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))


### Dependencies

* **actions:** bump actions/checkout ([#9](https://github.com/MysticRyuujin/mirror-bench/issues/9)) ([be49743](https://github.com/MysticRyuujin/mirror-bench/commit/be49743112ba6001b022bd3daec9c442a5925a66))
* **actions:** bump actions/setup-python in the actions group ([#12](https://github.com/MysticRyuujin/mirror-bench/issues/12)) ([930680d](https://github.com/MysticRyuujin/mirror-bench/commit/930680da12de59dc3171385bcb3672399586f66f))
* bump anyio, certifi, h2, hpack ([9977a7c](https://github.com/MysticRyuujin/mirror-bench/commit/9977a7c439590741123af2dec31548917d265186))
* bump idna to 3.18 (fixes PYSEC-2026-215) ([#10](https://github.com/MysticRyuujin/mirror-bench/issues/10)) ([690565c](https://github.com/MysticRyuujin/mirror-bench/commit/690565cc1669320eded4faaa175eb8ae85d739e4))

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

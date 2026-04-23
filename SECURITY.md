# Security Policy

## Supported Versions

`mirror-bench` is actively maintained at the latest `0.x` minor version. Older `0.x`
releases receive fixes only for critical issues on a best-effort basis.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Please do not open public GitHub issues for security reports.**

If you discover a vulnerability, use GitHub's private vulnerability reporting:

1. Go to <https://github.com/MysticRyuujin/mirror-bench/security/advisories/new>
2. Describe the issue, affected versions, and a minimal reproduction.
3. If the report involves exploitable behavior against a remote mirror, please
   avoid testing against production mirrors you don't own — mock or local
   reproductions are preferred.

You can expect:

- Acknowledgement within **3 business days**.
- A triage response (accepted / not accepted / more information needed) within
  **7 business days**.
- A fix and coordinated disclosure timeline agreed with the reporter for
  accepted issues. 90 days is the default maximum.

## Scope

In-scope:

- Arbitrary code execution triggered by parsing any mirror list or probe response.
- Credential or secret leakage in logs, output, or cached files.
- TLS verification bypass (accepting invalid certs outside of explicit user opt-in).
- Denial-of-service achievable with adversarial mirror list input.

Out of scope:

- Results of `mirror-bench` ranking itself (benchmarks are informational, not a
  trust anchor).
- Performance or correctness of third-party mirrors.
- Issues exploitable only with an attacker-controlled `--distro` or `--weights`
  flag running locally — those flags are user-trusted input.

## Supply Chain

- Releases are built via GitHub Actions with OIDC-based Trusted Publishing to
  PyPI (no long-lived tokens).
- Wheels and container images are signed with SLSA build provenance via
  `actions/attest-build-provenance`.
- Container images are published to `ghcr.io/MysticRyuujin/mirror-bench` with SBOMs
  attached at build time.
- Dependencies are monitored by Dependabot and pinned via `uv.lock`.

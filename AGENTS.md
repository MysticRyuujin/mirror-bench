# Agent guide — mirror-bench

Quick orientation for AI coding agents (Claude Code, Codex, etc.) working in
this repo. Humans should read `README.md` + `CONTRIBUTING.md` instead.

## Project shape

```text
src/mirror_bench/
  cli.py              typer app, subcommands `bench`, `list`, `completion`
  distro.py           /etc/os-release parsing + derivative alias table +
                      structured exceptions (UnsupportedDistroError, etc.)
  models.py           Mirror, ProbeResult, Score, Weights, BenchConfig, HostInfo
  discovery/          per-distro mirror fetchers (ABC + 5 impls +
                      UnknownDiscovererError)
  benchmark/
    transport.py      shared httpx.AsyncClient factory
    probe.py          two-phase async orchestration (TaskGroup + semaphore)
    tls.py            TLS version / cert inspection via response.extensions
    scorer.py         weighted composite ranking
  display.py          rich.Table + JSON/CSV emitters

tests/
  fixtures/           captured mirror-list bodies per distro
  test_*.py           respx-mocked units + @pytest.mark.integration opt-ins
                      (45 tests, 2 integration-gated)
```

## Commands (use these, not ad-hoc ones)

```sh
make install          # uv sync --all-extras
make hooks            # install pre-commit + commit-msg hook
make fmt              # ruff format
make lint             # ruff check
make typecheck        # mypy --strict on src AND tests (both checked)
make test             # pytest
make test-integration # opt-in: hits real mirror infrastructure
make security         # bandit + pip-audit
make pre-commit       # full pre-commit sweep (21 hooks)
make ci-local         # exactly what CI runs — gate before push
make docker-build     # build the release container
```

Run a single test: `uv run pytest tests/test_scorer.py::test_weights_shift_ranking -v`.

## Conventions that matter

- **Python 3.14, strict typing.** No `from __future__ import annotations` (PEP
  649 is default in 3.14). Prefer `list[T]` over `List[T]`, `X | None` over
  `Optional[X]`. Type-only imports go into `if TYPE_CHECKING:` blocks.
- **Tests must type-check.** Mypy runs against `src/` AND `tests/` under
  `strict = true`. Test functions use `-> None`; fixtures have explicit
  `client: httpx.AsyncClient` annotations.
- **Dataclasses, not pydantic.** `@dataclass(slots=True, frozen=True)`. No
  runtime validation layer.
- **Structured exceptions, not long-message raises.** For user-facing error
  paths, subclass a base exception and put the formatting in `__init__`
  (`UnsupportedDistroError(distro)` not
  `DistroDetectionError("unsupported ...")`). Callers can catch specifically
  and read structured attributes (`.distro`, `.supported`).
- **Async I/O via httpx + asyncio.TaskGroup.** Use the shared client from
  `benchmark.transport.build_client`; don't construct ad-hoc clients. Bind
  `tg.create_task(...)` to `_` — TaskGroup owns the lifecycle.
- **Discoverers return a list of `Mirror`.** Country filter happens at
  discovery time where the upstream API supports it (Ubuntu per-country,
  Fedora's `country=` param, Arch `country_code`), otherwise as a post-filter.
- **No writes to system config.** The tool never edits `sources.list`,
  `yum.repos.d`, pacman's `mirrorlist`. If you find yourself wanting to, stop
  and ask.
- **Options go after the subcommand** (`mirror-bench bench --distro ubuntu`,
  not `mirror-bench --distro ubuntu bench`) — typer convention.
- **`--json` / `--csv` mute rich output.** Both must pipe cleanly to `jq` /
  spreadsheets. Progress bars go to stderr.

## Linter philosophy

- Keep custom configuration **minimal**. Ruff selects 8 rule groups
  (`E,F,I,UP,B,SIM,RUF,ASYNC`) — resist the urge to expand.
- **Don't sweep issues under global ignores.** Fix the code instead. If a
  suppression is genuinely required, use a narrow inline comment with a
  one-line rationale (e.g. `# hadolint ignore=DL3008` in the Dockerfile).
- **No `# type: ignore` or `# noqa` in `src/` or `tests/`.** Currently zero
  exist — keep it that way. If mypy complains, fix the types.
- `uv.lock` is committed; do not gitignore it. Reproducible builds depend on it.

## Adding a new discoverer

1. `src/mirror_bench/discovery/<name>.py` implementing `MirrorDiscoverer`.
2. Register in `discovery/__init__.py::DISCOVERERS`.
3. Add ID aliases in `distro.py::_ALIASES`.
4. Respx-mocked test in `tests/test_discovery.py` + fixture file under
   `tests/fixtures/<name>_*`.
5. Update README supported-distros list and `AGENTS.md` project shape.

## What NOT to do

- Don't add pydantic, click directly (typer wraps it), or black (ruff format
  replaces it).
- Don't skip hooks (`--no-verify`), nor add `# type: ignore` / `# noqa` /
  `# nosec` without a one-line reason at the call site.
- Don't introduce new runtime dependencies without a strong reason — three
  (`httpx[http2]`, `typer`, `rich`) is the budget.
- Don't expand `[tool.ruff.lint] select` without a concrete bug class in mind.
- Don't emit rich output to stdout when `--json` or `--csv` is set.
- Don't rely on network access in unit tests. Network-touching tests must be
  marked `@pytest.mark.integration` and gated on `MIRROR_BENCH_INTEGRATION=1`.

## When something breaks

- **Mypy error.** Fix the types. `# type: ignore` is not allowed in this
  codebase — if you think you need one, you're probably modelling something
  wrong.
- **Integration test flaky.** Real mirrors come and go. If reproducible,
  tighten the assertion or bump tolerance. Don't add retries to runtime code
  just to paper over a test.
- **Docker build slow.** It's `uv sync` inside the builder. Use BuildKit cache
  mounts (already set up) or rely on GHA cache in CI.
- **Prettier and markdownlint disagree.** They coexist — prettier handles
  formatting, markdownlint handles content rules. If they conflict on a
  specific file, fix the file first, not the configs.

## License

AGPL-3.0-or-later. Modifications deployed over a network must be made
available in source form to users of that network service. Keep this in mind
if you're tempted to add anything that implies "hosted SaaS mirror-bench" —
that path carries source-disclosure obligations.

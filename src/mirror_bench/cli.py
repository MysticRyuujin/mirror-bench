"""mirror-bench command-line interface."""

import asyncio
import sys

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from mirror_bench import display
from mirror_bench import distro as distro_mod
from mirror_bench.benchmark import probe, scorer, transport
from mirror_bench.discovery import get_discoverer
from mirror_bench.models import (
    BenchConfig,
    HostInfo,
    Mirror,
    ProbeResult,
    Score,
    Weights,
)

app = typer.Typer(
    add_completion=True,
    no_args_is_help=False,
    help=(
        "Benchmark and rank Linux package mirrors across "
        "Ubuntu/Debian/Fedora/Mint/Arch.\n\n"
        "Install shell completion: `mirror-bench --install-completion`. "
        "Print completion script (to pipe or inspect): "
        "`mirror-bench --show-completion bash|zsh|fish|powershell`."
    ),
)


DistroOpt = typer.Option(
    None,
    "--distro",
    "-d",
    help="Override distro auto-detection. One of: ubuntu, debian, fedora, mint, arch.",
)
CountriesOpt = typer.Option(
    None,
    "--country",
    "-c",
    help="Comma-separated ISO 3166-1 alpha-2 country codes, e.g. US,CA,GB.",
)
ReleaseOpt = typer.Option(
    None,
    "--release",
    "-r",
    help=(
        "Distro release override. For ubuntu/debian/mint this is a codename "
        "(noble, bookworm, wilma); for fedora it's a numeric version (41, 42). "
        "Ignored for arch (rolling). Auto-detected when --distro is omitted."
    ),
)
TopOpt = typer.Option(
    15, "--top", "-n", help="Top-N mirrors to include in phase 2 / display."
)
ConcurrencyOpt = typer.Option(20, "--concurrency", help="Max concurrent HTTP probes.")
HttpsOnlyOpt = typer.Option(
    False, "--https-only", help="Exclude mirrors that don't serve HTTPS."
)
Tls13OnlyOpt = typer.Option(
    False, "--tls13-only", help="Exclude mirrors that don't negotiate TLS 1.3."
)
WeightsOpt = typer.Option(
    None,
    "--weights",
    help='Override scoring weights, e.g. "lat=0.4,thr=0.4,sec=0.2". Auto-normalized.',
)
JsonOpt = typer.Option(
    False, "--json", help="Emit JSON to stdout (suppresses table + progress)."
)
CsvOpt = typer.Option(
    False, "--csv", help="Emit CSV to stdout (suppresses table + progress)."
)
SkipThroughputOpt = typer.Option(
    False,
    "--no-throughput",
    help="Skip phase 2 (throughput). Phase 1 latency screen only.",
)


def _parse_countries(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(c.strip().upper() for c in raw.split(",") if c.strip())


def _parse_weights(raw: str | None) -> Weights:
    if not raw:
        return Weights()
    parts: dict[str, float] = {}
    for tok in raw.split(","):
        if "=" not in tok:
            msg = f"bad --weights token {tok!r}; expected key=value"
            raise typer.BadParameter(msg)
        k, _, v = tok.partition("=")
        try:
            parts[k.strip().lower()] = float(v.strip())
        except ValueError as e:
            msg = f"non-numeric weight {v!r}"
            raise typer.BadParameter(msg) from e
    aliases = {"lat": "latency", "thr": "throughput", "sec": "security"}
    mapped = {aliases.get(k, k): v for k, v in parts.items()}
    allowed = {"latency", "throughput", "security"}
    unknown = set(mapped) - allowed
    if unknown:
        msg = f"unknown weight keys: {sorted(unknown)}; expected {sorted(allowed)}"
        raise typer.BadParameter(msg)
    defaults = Weights()
    return Weights(
        latency=mapped.get("latency", defaults.latency),
        throughput=mapped.get("throughput", defaults.throughput),
        security=mapped.get("security", defaults.security),
    )


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """If no subcommand is given, default to `bench`."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(bench_cmd)


@app.command("bench")
def bench_cmd(
    distro: str | None = DistroOpt,
    release: str | None = ReleaseOpt,
    country: str | None = CountriesOpt,
    top: int = TopOpt,
    concurrency: int = ConcurrencyOpt,
    https_only: bool = HttpsOnlyOpt,
    tls13_only: bool = Tls13OnlyOpt,
    weights: str | None = WeightsOpt,
    json_out: bool = JsonOpt,
    csv_out: bool = CsvOpt,
    no_throughput: bool = SkipThroughputOpt,
) -> None:
    """Discover mirrors, run a two-phase benchmark, print the ranked table."""
    try:
        host = distro_mod.resolve(distro, release)
    except distro_mod.DistroDetectionError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    cfg = BenchConfig(
        distro=host.base_distro_id,
        countries=_parse_countries(country),
        top=top,
        concurrency=concurrency,
        https_only=https_only,
        tls13_only=tls13_only,
        weights=_parse_weights(weights),
        skip_throughput=no_throughput,
    )

    scores = asyncio.run(_run_bench(host, cfg, quiet=json_out or csv_out))

    if json_out:
        display.render_json(scores=scores, mirrors=None, host=host)
    elif csv_out:
        display.render_csv(scores=scores, mirrors=None)
    else:
        display.render_bench(scores, host)


@app.command("completion")
def completion_cmd(
    shell: str = typer.Argument(
        ...,
        help="Target shell: bash, zsh, or fish.",
        metavar="SHELL",
    ),
) -> None:
    """Print the shell completion script for a specific shell.

    Unlike `--install-completion` / `--show-completion`, this command does not
    depend on shell auto-detection and works reliably in sandboxes, CI, and
    containers. Pipe the output to your shell's completion directory.
    """
    from click.shell_completion import shell_complete

    shell = shell.lower()
    if shell not in {"bash", "zsh", "fish"}:
        typer.secho(
            f"unsupported shell {shell!r}; expected one of bash, zsh, fish",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    prog = "mirror-bench"
    env_var = "_MIRROR_BENCH_COMPLETE"
    cli = typer.main.get_command(app)
    rc = shell_complete(cli, {}, prog, env_var, f"{shell}_source")
    if rc != 0:
        raise typer.Exit(code=rc)


@app.command("list")
def list_cmd(
    distro: str | None = DistroOpt,
    release: str | None = ReleaseOpt,
    country: str | None = CountriesOpt,
    json_out: bool = JsonOpt,
    csv_out: bool = CsvOpt,
) -> None:
    """Discover mirrors and print them without benchmarking."""
    try:
        host = distro_mod.resolve(distro, release)
    except distro_mod.DistroDetectionError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    mirrors = asyncio.run(_run_discover(host, _parse_countries(country)))
    if json_out:
        display.render_json(scores=None, mirrors=mirrors, host=host)
    elif csv_out:
        display.render_csv(scores=None, mirrors=mirrors)
    else:
        display.render_list(mirrors, host)


async def _run_discover(host: HostInfo, countries: tuple[str, ...]) -> list[Mirror]:
    discoverer = get_discoverer(host.base_distro_id)
    async with transport.build_client() as client:
        return await discoverer.discover(client, host, countries)


async def _run_bench(host: HostInfo, cfg: BenchConfig, *, quiet: bool) -> list[Score]:
    discoverer = get_discoverer(host.base_distro_id)

    async with transport.build_client(tls13_only=cfg.tls13_only) as client:
        mirrors = await discoverer.discover(client, host, cfg.countries)
        if cfg.https_only:
            mirrors = [m for m in mirrors if m.is_https]

        if not mirrors:
            return []

        progress_columns = (
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        )
        console = display.stderr_console()

        if quiet:
            latency_results = await probe.latency_screen(
                client,
                mirrors,
                discoverer,
                host,
                concurrency=cfg.concurrency,
                samples=cfg.samples,
            )
        else:
            with Progress(*progress_columns, console=console, transient=True) as prog:
                task = prog.add_task("latency screen", total=len(mirrors))

                def on_prog(phase: str, done: int, total: int) -> None:
                    prog.update(task, completed=done, total=total)

                latency_results = await probe.latency_screen(
                    client,
                    mirrors,
                    discoverer,
                    host,
                    concurrency=cfg.concurrency,
                    samples=cfg.samples,
                    on_progress=on_prog,
                )

        if cfg.tls13_only:
            latency_results = scorer.filter_for_policy(
                latency_results, https_only=False, tls13_only=True
            )

        ok_results = [r for r in latency_results if r.ok]
        ok_results.sort(key=lambda r: r.ttfb_ms or float("inf"))
        top_for_phase2 = ok_results[: cfg.top]

        throughput_map: dict[str, ProbeResult] = {}
        if not cfg.skip_throughput and top_for_phase2:
            phase2_mirrors = [r.mirror for r in top_for_phase2]
            phase2_concurrency = min(8, cfg.concurrency)
            if quiet:
                throughput_map = await probe.throughput_test(
                    client,
                    phase2_mirrors,
                    discoverer,
                    host,
                    concurrency=phase2_concurrency,
                )
            else:
                with Progress(
                    *progress_columns, console=console, transient=True
                ) as prog:
                    task = prog.add_task("throughput", total=len(top_for_phase2))

                    def on_prog2(phase: str, done: int, total: int) -> None:
                        prog.update(task, completed=done, total=total)

                    throughput_map = await probe.throughput_test(
                        client,
                        phase2_mirrors,
                        discoverer,
                        host,
                        concurrency=phase2_concurrency,
                        on_progress=on_prog2,
                    )

        scores = scorer.score_results(top_for_phase2, throughput_map, cfg.weights)
        return scores[: cfg.top]


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.secho("interrupted", fg=typer.colors.YELLOW, err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()

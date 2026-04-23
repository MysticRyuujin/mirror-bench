"""Rendering: rich tables, JSON, CSV."""

import csv
import io
import json
import shutil
import sys
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mirror_bench.models import HostInfo, Mirror, Score


def render_bench(
    scores: Iterable[Score],
    host: HostInfo,
    *,
    console: Console | None = None,
) -> None:
    console = console or _stdout_console()
    scores_list = list(scores)
    if not scores_list:
        console.print("[yellow]No mirrors returned usable probes.[/yellow]")
        return

    release = host.codename or host.release_version or "?"
    n = len(scores_list)
    table = Table(
        title=f"mirror-bench — {host.base_distro_id} ({release}) — top {n}",
        show_lines=False,
        header_style="bold",
    )
    table.add_column("#", justify="right")
    table.add_column("Host", overflow="fold")
    table.add_column("CC")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Throughput", justify="right")
    table.add_column("HTTPS")
    table.add_column("TLS")
    table.add_column("HTTP/2")
    table.add_column("Score", justify="right")

    top_cut = max(1, n // 5)
    bottom_cut = n - top_cut

    for rank, s in enumerate(scores_list, start=1):
        if s.probe.error:
            color = "dim"
        elif rank <= top_cut:
            color = "green"
        elif rank > bottom_cut:
            color = "red"
        else:
            color = "yellow"

        table.add_row(
            f"[{color}]{rank}[/{color}]",
            s.mirror.host,
            s.mirror.country or "-",
            _fmt_ms(s.latency_ms),
            _fmt_bps(s.throughput_bps),
            _yes_no(s.mirror.is_https),
            s.probe.tls_version or "-",
            _yes_no(s.probe.http_version in {"HTTP/2", "HTTP/2.0"}),
            f"{s.composite:.3f}",
        )

    console.print(table)


def render_list(
    mirrors: Iterable[Mirror], host: HostInfo, *, console: Console | None = None
) -> None:
    console = console or _stdout_console()
    mirrors_list = list(mirrors)
    table = Table(
        title=f"Discovered mirrors — {host.base_distro_id} ({len(mirrors_list)} found)",
        header_style="bold",
    )
    table.add_column("Host", overflow="fold")
    table.add_column("CC")
    table.add_column("Protocols")
    table.add_column("URL", overflow="fold")
    for m in mirrors_list:
        table.add_row(
            m.host,
            m.country or "-",
            ",".join(m.protocols) or "-",
            m.url,
        )
    console.print(table)


def render_json(
    scores: Iterable[Score] | None,
    mirrors: Iterable[Mirror] | None,
    host: HostInfo,
    *,
    stream: Any | None = None,
) -> None:
    stream = stream or sys.stdout
    payload: dict[str, Any] = {"host_info": _host_info_dict(host)}
    if scores is not None:
        payload["results"] = [_score_dict(s) for s in scores]
    if mirrors is not None:
        payload["mirrors"] = [_mirror_dict(m) for m in mirrors]
    json.dump(payload, stream, indent=2, default=str)
    stream.write("\n")


def render_csv(
    scores: Iterable[Score] | None,
    mirrors: Iterable[Mirror] | None,
    *,
    stream: Any | None = None,
) -> None:
    stream = stream or sys.stdout
    if scores is not None:
        fieldnames = [
            "rank",
            "host",
            "url",
            "country",
            "latency_ms",
            "throughput_bps",
            "https",
            "tls_version",
            "http_version",
            "cert_valid",
            "security_score",
            "composite",
            "error",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for rank, s in enumerate(list(scores), start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "host": s.mirror.host,
                    "url": s.mirror.url,
                    "country": s.mirror.country or "",
                    "latency_ms": f"{s.latency_ms:.2f}"
                    if s.latency_ms is not None
                    else "",
                    "throughput_bps": (
                        f"{s.throughput_bps:.0f}"
                        if s.throughput_bps is not None
                        else ""
                    ),
                    "https": "true" if s.mirror.is_https else "false",
                    "tls_version": s.probe.tls_version or "",
                    "http_version": s.probe.http_version or "",
                    "cert_valid": ""
                    if s.probe.cert_valid is None
                    else str(s.probe.cert_valid),
                    "security_score": f"{s.security_score:.2f}",
                    "composite": f"{s.composite:.4f}",
                    "error": s.probe.error or "",
                }
            )
        return

    if mirrors is not None:
        fieldnames = ["host", "url", "country", "protocols"]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for m in mirrors:
            writer.writerow(
                {
                    "host": m.host,
                    "url": m.url,
                    "country": m.country or "",
                    "protocols": ",".join(m.protocols),
                }
            )


def _render_width() -> int:
    """Host terminal width when detectable, else 120 (wider than rich's 80
    default — readable inside `docker run` without `-it`, in CI logs, etc.).
    """
    width, _ = shutil.get_terminal_size(fallback=(120, 24))
    return width


def _stdout_console() -> Console:
    # force_terminal=True renders color even when stdout is a pipe, which is
    # the default shape inside `docker run` without `-t`. Users who want
    # plain text (e.g. `docker run … bench > file.txt`) can set NO_COLOR=1;
    # rich honors that env var regardless of force_terminal.
    return Console(force_terminal=True, width=_render_width())


def stderr_console() -> Console:
    return Console(stderr=True, force_terminal=True, width=_render_width())


def table_to_string(scores: Iterable[Score], host: HostInfo) -> str:
    """Render a bench table to a plain string (for non-TTY captures / tests)."""
    buf = io.StringIO()
    console = Console(file=buf, width=120, color_system=None)
    render_bench(scores, host, console=console)
    return buf.getvalue()


def _yes_no(flag: bool | None) -> str:
    if flag is True:
        return "[green]yes[/green]"
    if flag is False:
        return "[red]no[/red]"
    return "-"


def _fmt_ms(v: float | None) -> str:
    return f"{v:.0f}" if v is not None else "-"


def _fmt_bps(bps: float | None) -> str:
    if bps is None:
        return "-"
    mb = bps / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} MB/s"
    kb = bps / 1024
    return f"{kb:.0f} KB/s"


def _mirror_dict(m: Mirror) -> dict[str, Any]:
    return {
        "url": m.url,
        "host": m.host,
        "country": m.country,
        "protocols": list(m.protocols),
    }


def _score_dict(s: Score) -> dict[str, Any]:
    return {
        "rank_key": s.composite,
        "mirror": _mirror_dict(s.mirror),
        "latency_ms": s.latency_ms,
        "throughput_bps": s.throughput_bps,
        "security_score": s.security_score,
        "composite": s.composite,
        "http_version": s.probe.http_version,
        "tls_version": s.probe.tls_version,
        "cert_valid": s.probe.cert_valid,
        "status": s.probe.status,
        "error": s.probe.error,
    }


def _host_info_dict(host: HostInfo) -> dict[str, Any]:
    return {
        "distro_id": host.distro_id,
        "base_distro_id": host.base_distro_id,
        "codename": host.codename,
        "release_version": host.release_version,
        "arch": host.arch,
    }

"""Output rendering tests."""

import csv
import io
import json
from dataclasses import replace

from mirror_bench import display
from mirror_bench.benchmark.scorer import score_results
from mirror_bench.models import Score, Weights
from tests.conftest import make_host
from tests.test_scorer import make_probe


def _scores() -> list[Score]:
    measured = make_probe(url="https://measured.example.org/u/")
    failed = make_probe(url="https://failed.example.org/u/")
    tput_map = {
        measured.mirror.url: make_probe(url=measured.mirror.url, bps=2_097_152.0),
        failed.mirror.url: make_probe(
            url=failed.mirror.url, bps=None, status=404, error="http_404"
        ),
    }
    return score_results([measured, failed], tput_map, Weights())


def test_json_reports_throughput_error() -> None:
    buf = io.StringIO()
    display.render_json(scores=_scores(), mirrors=None, host=make_host(), stream=buf)
    by_host = {r["mirror"]["host"]: r for r in json.loads(buf.getvalue())["results"]}
    assert by_host["measured.example.org"]["throughput_bps"] == 2_097_152.0
    assert by_host["measured.example.org"]["throughput_error"] is None
    assert by_host["failed.example.org"]["throughput_bps"] is None
    assert by_host["failed.example.org"]["throughput_error"] == "http_404"


def test_csv_reports_throughput_error() -> None:
    buf = io.StringIO()
    display.render_csv(scores=_scores(), mirrors=None, stream=buf)
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    by_host = {row["host"]: row for row in rows}
    assert by_host["measured.example.org"]["throughput_error"] == ""
    assert by_host["failed.example.org"]["throughput_error"] == "http_404"
    assert by_host["failed.example.org"]["throughput_bps"] == ""


def test_table_shows_dash_for_missing_throughput() -> None:
    table = display.table_to_string(_scores(), make_host())
    measured_row = next(ln for ln in table.splitlines() if "measured.example" in ln)
    failed_row = next(ln for ln in table.splitlines() if "failed.example" in ln)
    assert "2.0 MB/s" in measured_row
    assert "MB/s" not in failed_row
    assert "KB/s" not in failed_row


def test_no_throughput_run_shows_no_rate() -> None:
    scores = score_results([make_probe(bps=20_000.0)], None, Weights())
    table = display.table_to_string(scores, make_host())
    assert "KB/s" not in table


def test_http3_advertisement_is_reported() -> None:
    with_h3 = replace(make_probe(url="https://h3.example.org/u/"), h3_port=443)
    without = make_probe(url="https://plain.example.org/u/")
    scores = score_results([with_h3, without], None, Weights())

    buf = io.StringIO()
    display.render_json(scores=scores, mirrors=None, host=make_host(), stream=buf)
    by_host = {r["mirror"]["host"]: r for r in json.loads(buf.getvalue())["results"]}
    assert by_host["h3.example.org"]["h3_advertised"] is True
    assert by_host["plain.example.org"]["h3_advertised"] is False

    buf = io.StringIO()
    display.render_csv(scores=scores, mirrors=None, stream=buf)
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert {row["host"]: row["h3_advertised"] for row in rows} == {
        "h3.example.org": "true",
        "plain.example.org": "false",
    }

    table = display.table_to_string(scores, make_host())
    assert "HTTP/3" in table
    h3_row = next(ln for ln in table.splitlines() if "h3.example" in ln)
    plain_row = next(ln for ln in table.splitlines() if "plain.example" in ln)
    assert "adv" in h3_row
    assert "adv" not in plain_row


def test_http3_probe_result_is_reported() -> None:
    confirmed = replace(make_probe(url="https://ok.example.org/u/"), h3_port=443)
    silent = replace(make_probe(url="https://silent.example.org/u/"), h3_port=443)
    scores = [
        replace(
            s,
            h3_probe=make_probe(url=s.mirror.url, ttfb_ms=12.5, http="HTTP/3")
            if s.mirror.host == "ok.example.org"
            else make_probe(
                url=s.mirror.url, ttfb_ms=None, status=None, error="ConnectionError"
            ),
        )
        for s in score_results([confirmed, silent], None, Weights())
    ]

    buf = io.StringIO()
    display.render_json(scores=scores, mirrors=None, host=make_host(), stream=buf)
    by_host = {r["mirror"]["host"]: r for r in json.loads(buf.getvalue())["results"]}
    assert by_host["ok.example.org"]["h3_latency_ms"] == 12.5
    assert by_host["ok.example.org"]["h3_error"] is None
    assert by_host["silent.example.org"]["h3_latency_ms"] is None
    assert by_host["silent.example.org"]["h3_error"] == "ConnectionError"

    buf = io.StringIO()
    display.render_csv(scores=scores, mirrors=None, stream=buf)
    rows = {r["host"]: r for r in csv.DictReader(io.StringIO(buf.getvalue()))}
    assert rows["ok.example.org"]["h3_latency_ms"] == "12.50"
    assert rows["silent.example.org"]["h3_error"] == "ConnectionError"

    table = display.table_to_string(scores, make_host())
    ok_row = next(ln for ln in table.splitlines() if "ok.example" in ln)
    silent_row = next(ln for ln in table.splitlines() if "silent.example" in ln)
    assert "adv" not in ok_row
    assert "adv" in silent_row

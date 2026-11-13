"""Output rendering tests."""

import csv
import io
import json

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


def test_csv_reports_throughput_error_in_last_column() -> None:
    buf = io.StringIO()
    display.render_csv(scores=_scores(), mirrors=None, stream=buf)
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[0][-1] == "throughput_error"
    by_host = {row[1]: row for row in rows[1:]}
    assert by_host["measured.example.org"][-1] == ""
    assert by_host["failed.example.org"][-1] == "http_404"
    assert by_host["failed.example.org"][rows[0].index("throughput_bps")] == ""


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

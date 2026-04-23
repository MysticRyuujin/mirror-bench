"""CLI tests using typer.testing.CliRunner."""

import json

import respx
from typer.testing import CliRunner

from mirror_bench.cli import app

runner = CliRunner()

_COUNTRY_SWEEP_RE = r"http://mirrors\.ubuntu\.com/[A-Z]{2}\.txt"


def _mock_ubuntu_fallback_list(body: str) -> None:
    """Mock per-country sweep as 404 and mirrors.txt as the fallback body."""
    respx.get(url__regex=_COUNTRY_SWEEP_RE).respond(404)
    respx.get("http://mirrors.ubuntu.com/mirrors.txt").respond(200, text=body)


@respx.mock
def test_list_ubuntu_renders_table(tmp_path: object) -> None:
    _mock_ubuntu_fallback_list("http://mir-a.org/ubuntu/\nhttps://mir-b.org/ubuntu/\n")
    result = runner.invoke(app, ["list", "--distro", "ubuntu"])
    assert result.exit_code == 0, result.output
    assert "mir-a.org" in result.output
    assert "mir-b.org" in result.output
    assert "Discovered mirrors" in result.output


@respx.mock
def test_list_json_output_valid() -> None:
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    result = runner.invoke(app, ["list", "--distro", "ubuntu", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["host_info"]["base_distro_id"] == "ubuntu"
    assert len(payload["mirrors"]) == 1
    assert payload["mirrors"][0]["host"] == "mir-a.org"


@respx.mock
def test_bench_no_throughput_renders_table() -> None:
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(
        app,
        [
            "bench",
            "--distro",
            "ubuntu",
            "--no-throughput",
            "--top",
            "1",
            "--concurrency",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "mir-a.org" in result.output


def test_bench_unknown_distro_errors() -> None:
    result = runner.invoke(app, ["bench", "--distro", "slackware"])
    assert result.exit_code == 2


@respx.mock
def test_bench_json_output() -> None:
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(
        app,
        [
            "bench",
            "--distro",
            "ubuntu",
            "--no-throughput",
            "--top",
            "1",
            "--concurrency",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "results" in payload
    assert payload["host_info"]["base_distro_id"] == "ubuntu"


@respx.mock
def test_weights_parse() -> None:
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(
        app,
        [
            "bench",
            "--distro",
            "ubuntu",
            "--no-throughput",
            "--top",
            "1",
            "--concurrency",
            "1",
            "--weights",
            "lat=0.5,thr=0.25,sec=0.25",
        ],
    )
    assert result.exit_code == 0, result.output


def test_weights_bad_token_errors() -> None:
    result = runner.invoke(
        app, ["bench", "--distro", "ubuntu", "--weights", "latency-0.5"]
    )
    assert result.exit_code != 0


def test_weights_unknown_key_errors() -> None:
    result = runner.invoke(
        app, ["bench", "--distro", "ubuntu", "--weights", "bogus=0.5"]
    )
    assert result.exit_code != 0


def test_completion_emits_bash_script() -> None:
    result = runner.invoke(app, ["completion", "bash"])
    assert result.exit_code == 0, result.output
    assert "_MIRROR_BENCH_COMPLETE" in result.output


def test_completion_emits_zsh_script() -> None:
    result = runner.invoke(app, ["completion", "zsh"])
    assert result.exit_code == 0, result.output
    assert "compdef" in result.output or "_MIRROR_BENCH_COMPLETE" in result.output


def test_completion_emits_fish_script() -> None:
    result = runner.invoke(app, ["completion", "fish"])
    assert result.exit_code == 0, result.output
    assert "complete" in result.output


def test_completion_rejects_unknown_shell() -> None:
    result = runner.invoke(app, ["completion", "tcsh"])
    assert result.exit_code == 2
    assert "unsupported shell" in result.output


@respx.mock
def test_release_flag_targets_codename_for_apt() -> None:
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    # Probe should hit jammy (overridden), NOT the default noble.
    route = respx.get("https://mir-a.org/ubuntu/dists/jammy/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(
        app,
        [
            "bench",
            "--distro",
            "ubuntu",
            "--release",
            "jammy",
            "--no-throughput",
            "--top",
            "1",
            "--concurrency",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert route.called, "expected probe against dists/jammy/InRelease"


def test_release_flag_short_form_accepted() -> None:
    # Just verifying CLI parsing accepts `-r`. Arch has no network mock here,
    # so we stop at argument parsing: exit code 2 would mean a BadParameter.
    result = runner.invoke(app, ["list", "--distro", "arch", "-r", "ignored", "--help"])
    assert result.exit_code == 0, result.output

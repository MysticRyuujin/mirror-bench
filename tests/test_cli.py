"""CLI tests using typer.testing.CliRunner."""

import json
from unittest import mock

import httpx
import pytest
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
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
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
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
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
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
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
    route = respx.get("https://mir-a.org/ubuntu/dists/jammy-updates/InRelease").respond(
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
    assert route.called, "expected probe against dists/jammy-updates/InRelease"


def test_release_flag_short_form_accepted() -> None:
    # Just verifying CLI parsing accepts `-r`. Arch has no network mock here,
    # so we stop at argument parsing: exit code 2 would mean a BadParameter.
    result = runner.invoke(app, ["list", "--distro", "arch", "-r", "ignored", "--help"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_no_subcommand_runs_bench_with_option_defaults() -> None:
    fake = {"ID": "ubuntu", "VERSION_CODENAME": "noble", "VERSION_ID": "24.04"}
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
        206, content=b"x" * 1024
    )
    respx.get("https://mir-a.org/ubuntu/dists/noble/Contents-amd64.gz").respond(
        200, content=b"y" * (512 * 1024)
    )
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "mir-a.org" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["bench", "--distro", "ubuntu", "--concurrency", "0"],
        ["bench", "--distro", "ubuntu", "--top", "0"],
        ["bench", "--distro", "ubuntu", "--top", "-3"],
        ["bench", "--distro", "ubuntu", "--json", "--csv"],
        ["list", "--distro", "ubuntu", "--json", "--csv"],
        ["bench", "--distro", "ubuntu", "--max-age", "-1"],
        ["bench", "--distro", "ubuntu", "--max-age", "nan"],
        ["bench", "--distro", "ubuntu", "--max-age", "inf"],
        ["bench", "--distro", "ubuntu", "--weights", "lat=-1"],
        ["bench", "--distro", "ubuntu", "--weights", "lat=nan"],
        ["bench", "--distro", "ubuntu", "--weights", "lat=inf"],
        ["bench", "--distro", "ubuntu", "--weights", "lat=0,thr=0,sec=0"],
        [
            "bench",
            "--distro",
            "ubuntu",
            "--no-throughput",
            "--weights",
            "thr=1,lat=0,sec=0",
        ],
    ],
)
def test_invalid_option_values_are_usage_errors(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("command", ["bench", "list"])
@respx.mock
def test_discovery_failure_exits_1_without_traceback(command: str) -> None:
    respx.get(url__regex=_COUNTRY_SWEEP_RE).mock(side_effect=httpx.ConnectError("boom"))
    respx.get("http://mirrors.ubuntu.com/mirrors.txt").mock(
        side_effect=httpx.ConnectError("boom")
    )
    result = runner.invoke(app, [command, "--distro", "ubuntu"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "could not discover ubuntu mirrors" in result.output


@respx.mock
def test_bench_keeps_one_row_when_https_and_http_both_work() -> None:
    respx.get("https://mirror-master.debian.org/status/Mirrors.masterlist").respond(
        200, text="Site: mir-a.org\nCountry: US United States\nArchive-http: /debian/\n"
    )
    for scheme in ("https", "http"):
        respx.get(
            f"{scheme}://mir-a.org/debian/dists/trixie-updates/InRelease"
        ).respond(206, content=b"x" * 1024)
    result = runner.invoke(
        app, ["bench", "--distro", "debian", "--no-throughput", "--json"]
    )
    assert result.exit_code == 0, result.output
    results = json.loads(result.output)["results"]
    assert [r["mirror"]["url"] for r in results] == ["https://mir-a.org/debian/"]
    assert results[0]["throughput_bps"] is None
    assert results[0]["throughput_error"] is None


_FEDORA_OS = "fedora/linux/releases/45/Everything/x86_64/os/"


def _fedora_probe(scheme: str, host: str) -> respx.Route:
    """Route for the latency probe: the updates tree beside releases/."""
    return respx.get(
        url__regex=(
            rf"{scheme}://{host}\.example\.org/fedora/linux/updates/45/"
            r"Everything/[^/]+/repodata/repomd\.xml"
        )
    )


def _mock_fedora_us_list(*hosts: str) -> None:
    respx.get(
        url__regex=r"https://mirrors\.fedoraproject\.org/mirrorlist\?.*country=us"
    ).respond(
        200,
        text="# repo = fedora-45 arch = x86_64 country = us\n"
        + "".join(f"http://{h}.example.org/{_FEDORA_OS}\n" for h in hosts),
    )


def _repomd(revision: int) -> bytes:
    return f"<repomd><revision>{revision}</revision></repomd>".encode()


_FEDORA_BENCH = ["bench", "--distro", "fedora", "--country", "US", "--no-throughput"]


@respx.mock
def test_bench_prefers_https_for_a_mirror_listed_as_http() -> None:
    _mock_fedora_us_list("both", "plain")
    _fedora_probe("https", "both").respond(206, content=_repomd(1_794_000_000))
    _fedora_probe("http", "both").respond(206, content=_repomd(1_794_000_000))
    _fedora_probe("http", "plain").respond(206, content=_repomd(1_794_000_000))
    _fedora_probe("https", "plain").mock(side_effect=httpx.ConnectError("no 443"))
    result = runner.invoke(app, [*_FEDORA_BENCH, "--json"])
    assert result.exit_code == 0, result.output
    urls = {r["mirror"]["url"] for r in json.loads(result.stdout)["results"]}
    assert urls == {
        f"https://both.example.org/{_FEDORA_OS}",
        f"http://plain.example.org/{_FEDORA_OS}",
    }


def _mock_fresh_and_stale(stale_age_s: int) -> None:
    newest = 1_794_000_000
    _mock_fedora_us_list("fresh", "stale")
    for scheme in ("https", "http"):
        _fedora_probe(scheme, "fresh").respond(206, content=_repomd(newest))
        _fedora_probe(scheme, "stale").respond(
            206, content=_repomd(newest - stale_age_s)
        )


@respx.mock
def test_bench_drops_stale_mirrors_by_default() -> None:
    _mock_fresh_and_stale(12 * 86400)
    result = runner.invoke(app, [*_FEDORA_BENCH, "--json"])
    assert result.exit_code == 0, result.output
    results = json.loads(result.stdout)["results"]
    assert [r["mirror"]["host"] for r in results] == ["fresh.example.org"]
    assert results[0]["sync_age_s"] == 0
    assert "dropped 1 mirror more than 36 h behind the newest" in result.stderr


@respx.mock
def test_bench_keeps_a_mirror_one_day_behind() -> None:
    _mock_fresh_and_stale(23 * 3600)
    result = runner.invoke(app, [*_FEDORA_BENCH, "--json"])
    assert result.exit_code == 0, result.output
    ages = {
        r["mirror"]["host"]: r["sync_age_s"]
        for r in json.loads(result.stdout)["results"]
    }
    assert ages == {"fresh.example.org": 0, "stale.example.org": 23 * 3600}
    assert "dropped" not in result.stderr


@respx.mock
def test_bench_max_age_zero_keeps_stale_mirrors() -> None:
    _mock_fresh_and_stale(12 * 86400)
    result = runner.invoke(app, [*_FEDORA_BENCH, "--max-age", "0", "--json"])
    assert result.exit_code == 0, result.output
    ages = {
        r["mirror"]["host"]: r["sync_age_s"]
        for r in json.loads(result.stdout)["results"]
    }
    assert ages == {"fresh.example.org": 0, "stale.example.org": 12 * 86400}
    assert "dropped" not in result.stderr


@respx.mock
def test_bench_keeps_current_http_twin_of_a_stale_https_endpoint() -> None:
    newest = 1_794_000_000
    _mock_fedora_us_list("split", "other")
    _fedora_probe("https", "split").respond(206, content=_repomd(newest - 5 * 86400))
    _fedora_probe("http", "split").respond(206, content=_repomd(newest))
    _fedora_probe("https", "other").respond(206, content=_repomd(newest))
    _fedora_probe("http", "other").respond(206, content=_repomd(newest))
    result = runner.invoke(app, [*_FEDORA_BENCH, "--json"])
    assert result.exit_code == 0, result.output
    urls = {r["mirror"]["url"] for r in json.loads(result.stdout)["results"]}
    assert urls == {
        f"http://split.example.org/{_FEDORA_OS}",
        f"https://other.example.org/{_FEDORA_OS}",
    }
    # The site still has a current endpoint, so it is not counted as dropped.
    assert "dropped" not in result.stderr


@respx.mock
def test_bench_without_a_tty_writes_no_control_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(app, ["bench", "--distro", "ubuntu", "--no-throughput"])
    assert result.exit_code == 0, result.output
    assert "mir-a.org" in result.stdout
    assert "\x1b" not in result.stdout
    assert "\x1b" not in result.stderr
    assert "latency screen" not in result.stderr


@respx.mock
def test_bench_table_keeps_color_through_a_pipe_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    _mock_ubuntu_fallback_list("https://mir-a.org/ubuntu/\n")
    respx.get("https://mir-a.org/ubuntu/dists/noble-updates/InRelease").respond(
        206, content=b"x" * 1024
    )
    result = runner.invoke(app, ["bench", "--distro", "ubuntu", "--no-throughput"])
    assert result.exit_code == 0, result.output
    assert "\x1b[" in result.stdout
    assert "\x1b" not in result.stderr

"""Distro auto-detection logic."""

from unittest import mock

import pytest

from mirror_bench import distro


def test_from_override_known() -> None:
    host = distro.from_override("ubuntu")
    assert host.base_distro_id == "ubuntu"
    assert host.codename == "noble"


def test_from_override_release_for_apt_sets_codename() -> None:
    host = distro.from_override("ubuntu", release="jammy")
    assert host.codename == "jammy"
    assert host.release_version is None


def test_from_override_release_for_fedora_sets_version() -> None:
    host = distro.from_override("fedora", release="42")
    assert host.codename is None
    assert host.release_version == "42"


def test_from_override_release_ignored_for_arch() -> None:
    host = distro.from_override("arch", release="anything")
    assert host.codename is None
    assert host.release_version is None


def test_resolve_release_shadows_auto_detected_codename() -> None:
    fake = {"ID": "ubuntu", "VERSION_CODENAME": "noble", "VERSION_ID": "24.04"}
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        host = distro.resolve(None, release_override="jammy")
    assert host.base_distro_id == "ubuntu"
    assert host.codename == "jammy"


def test_resolve_release_shadows_auto_detected_fedora_version() -> None:
    fake = {"ID": "fedora", "VERSION_ID": "41"}
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        host = distro.resolve(None, release_override="42")
    assert host.base_distro_id == "fedora"
    assert host.release_version == "42"


def test_from_override_alias_resolves_to_base() -> None:
    host = distro.from_override("pop")
    assert host.base_distro_id == "ubuntu"


def test_from_override_unknown_raises() -> None:
    with pytest.raises(distro.UnsupportedDistroError):
        distro.from_override("slackware")


def test_resolve_uses_override() -> None:
    host = distro.resolve("debian")
    assert host.base_distro_id == "debian"
    assert host.codename == "bookworm"


def test_detect_returns_none_when_os_release_missing() -> None:
    with mock.patch("platform.freedesktop_os_release", side_effect=OSError):
        assert distro.detect() is None


def test_detect_parses_ubuntu_os_release() -> None:
    fake = {
        "ID": "ubuntu",
        "VERSION_CODENAME": "noble",
        "VERSION_ID": "24.04",
    }
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        host = distro.detect()
    assert host is not None
    assert host.base_distro_id == "ubuntu"
    assert host.codename == "noble"
    assert host.release_version == "24.04"


def test_detect_falls_back_to_id_like() -> None:
    fake = {
        "ID": "pop",
        "ID_LIKE": "ubuntu debian",
        "VERSION_CODENAME": "jammy",
        "VERSION_ID": "22.04",
    }
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        host = distro.detect()
    assert host is not None
    # pop is in the alias table directly
    assert host.base_distro_id == "ubuntu"


def test_detect_codename_fallback_for_missing_codename() -> None:
    fake = {"ID": "debian", "VERSION_ID": "12"}
    with mock.patch("platform.freedesktop_os_release", return_value=fake):
        host = distro.detect()
    assert host is not None
    assert host.codename == "bookworm"


def test_resolve_raises_when_detection_fails_and_no_override() -> None:
    with (
        mock.patch("platform.freedesktop_os_release", side_effect=OSError),
        pytest.raises(distro.OSReleaseMissingError),
    ):
        distro.resolve(None)


def test_apt_arch_normalization() -> None:
    host = distro.from_override("ubuntu")
    assert host.apt_arch in {"amd64", "arm64"}  # depends on the test host

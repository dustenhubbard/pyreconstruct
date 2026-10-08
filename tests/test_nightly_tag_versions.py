"""Both nightly tag shapes read as versions in time order.

Nightlies were tagged vX.Y.Z.devYYYYMMDD until 2026-10-08, one a day. Since
then the dev number is the UTC date and time, YYYYMMDDHHMM, so a manual run
can ship a second nightly the same day. PEP 440 compares the dev number as an
integer, so every 12-digit tag sorts above every 8-digit one, and later times
sort higher. Both shapes keep the same X.Y.Z release part.
"""

from packaging.version import Version

from PyReconstruct.modules.backend.updater import updater as U


DATED = "v1.24.0.dev20261008"            # this morning's 8-digit nightly
TIMED = "v1.24.0.dev202610081315"        # a second one the same day, 13:15 UTC
LATER = "v1.24.0.dev202610081840"


def _version(tag):
    return U._tag_version({"tag_name": tag})


def test_both_shapes_parse():
    assert _version(DATED) == Version("1.24.0.dev20261008")
    assert _version(TIMED) == Version("1.24.0.dev202610081315")


def test_they_sort_in_time_order():
    tags = ["v1.24.0", LATER, "v1.23.0", TIMED, "v1.24.0.dev20261007", DATED]
    assert sorted(tags, key=_version) == [
        "v1.23.0", "v1.24.0.dev20261007", DATED, TIMED, LATER, "v1.24.0"]


def test_both_strip_to_the_same_release():
    assert _version(DATED).base_version == _version(TIMED).base_version == "1.24.0"


def test_a_timed_nightly_is_newer_than_the_same_days_dated_one():
    assert U.compare_versions(_version(TIMED), _version(DATED)) == "newer"
    assert U.compare_versions(_version(DATED), _version(TIMED)) == "older"


def test_the_updater_takes_both_shapes_as_nightly_tags():
    for tag in (DATED, TIMED):
        assert U._NIGHTLY_TAG_RE.fullmatch(tag), tag
    for tag in ("v1.24.0.dev2026100813", "v1.24.0.dev3", "v1.24.0"):
        assert not U._NIGHTLY_TAG_RE.fullmatch(tag), tag


def test_asset_names_carry_the_timed_version():
    name = "PyReconstruct-1.24.0.dev202610081315-macOS-arm64-Dev.dmg"
    assert U.asset_version(name) == Version("1.24.0.dev202610081315")

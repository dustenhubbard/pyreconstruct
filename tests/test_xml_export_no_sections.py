"""XML export of a series with no sections refuses before it writes anything.

`jsonToXML` read `snum` and `thickness` from its section loop to fill in the
.ser, so with no sections it raised `UnboundLocalError`. It now raises a
`ValueError` that says why, before any file is written. PyReconstruct does
not open or save a series with no sections, so only a script reaches this.
"""
import pytest

from PyReconstruct.modules.backend.func import jsonToXML
from PyReconstruct.modules.backend.progress import NullProgressReporter


def test_no_sections_refuses_and_writes_nothing(real_series, tmp_path):
    real_series.setProgressReporter(NullProgressReporter)
    real_series.sections = {}
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="no sections"):
        jsonToXML(real_series, str(out), "empty")

    assert list(out.iterdir()) == []


def test_a_series_with_sections_still_exports(real_series, tmp_path):
    real_series.setProgressReporter(NullProgressReporter)
    out = tmp_path / "out"
    out.mkdir()

    jsonToXML(real_series, str(out), "full")

    assert (out / "full.ser").exists()
    for snum in real_series.sections:
        assert (out / f"full.{snum}").exists()

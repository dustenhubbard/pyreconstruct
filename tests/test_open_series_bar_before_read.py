"""The "Opening series..." dialog exists before the file is read.

A 249 MB lab series read off the file server took seconds before anything
appeared, because openJser read and parsed the whole file and only then
built its progress reporter (September 2026). The reporter is now built
first, and every early exit finishes it so no dialog is left standing.
"""
import os
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes.series import Series, SeriesOpenError
from PyReconstruct.modules.backend.progress import NullProgressReporter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class Recording(NullProgressReporter):
    log = []

    def __init__(self, text="", cancel=True):
        super().__init__(text, cancel)
        Recording.log.append(("made", text))

    def finish(self):
        Recording.log.append(("finished", self.text))
        super().finish()


@pytest.fixture(autouse=True)
def clear_log():
    Recording.log = []
    yield


def test_the_reporter_exists_before_the_file_is_read(series_jser, monkeypatch):
    real = series_module.fast_loads

    def spying(data):
        Recording.log.append(("read", len(data)))
        return real(data)

    monkeypatch.setattr(series_module, "fast_loads", spying)
    s = Series.openJser(str(series_jser), progress=Recording)
    try:
        kinds = [k for k, _ in Recording.log]
        assert kinds.index("made") < kinds.index("read")
        assert kinds[-1] == "finished"
    finally:
        s.close()


def test_a_corrupt_file_still_closes_the_dialog(tmp_path):
    bad = tmp_path / "broken.jser"
    bad.write_text("this is not json")
    with pytest.raises(SeriesOpenError):
        Series.openJser(str(bad), progress=Recording)
    assert Recording.log == [("made", "Opening series..."), ("finished", "Opening series...")]


def test_declining_the_merge_closes_the_dialog(series_jser, monkeypatch):
    monkeypatch.setattr(series_module, "contourNameCollisions", lambda data: {"a": ["a", "a "]})
    decline = SimpleNamespace(confirm=lambda message: False)
    result = Series.openJser(str(series_jser), progress=Recording, notifier=decline)
    assert result is None
    assert Recording.log[-1] == ("finished", "Opening series...")

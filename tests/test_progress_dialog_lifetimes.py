"""Progress dialogs must come down however their operation ends.

Three findings from the review fleet (2026-08-28), one disease: a reporter
that reaches 100% only on the happy path. The enumerateSections dialog has
no cancel button, so an abandoned iteration left a window-modal dialog
blocking the app with force-quit as the only exit; openJser's dialog
survived any exception behind the error dialog that followed.

The third finding is a thread bug with the same victim: generateVolumes,
running in the 3D worker thread, opened a series with the DEFAULT reporter,
which builds a QProgressDialog parented to the main window from off the GUI
thread. It now passes the null reporter and notifier.
"""

import pytest

from PyReconstruct.modules.backend.progress import ProgressReporter

pytestmark = pytest.mark.gui


class RecordingReporter(ProgressReporter):
    """A reporter that remembers whether anything finished it."""

    instances = []

    def __init__(self, text="", cancel=True):
        super().__init__(text, cancel)
        self.values = []
        RecordingReporter.instances.append(self)

    def set_progress(self, percent):
        self.values.append(percent)

    def was_canceled(self):
        return False

    @property
    def finished(self):
        return bool(self.values) and self.values[-1] == 100


@pytest.fixture
def recording(real_series):
    RecordingReporter.instances = []
    real_series.setProgressReporter(RecordingReporter)
    yield RecordingReporter
    real_series.setProgressReporter(None)


def test_a_break_still_closes_the_progress_dialog(real_series, recording):
    for snum, section in real_series.enumerateSections():
        break  # the caller changed its mind two sections in

    assert recording.instances, "no reporter was ever built"
    assert all(r.finished for r in recording.instances)


def test_an_exception_in_the_loop_body_still_closes_it(real_series, recording):
    class BodyError(Exception):
        pass

    with pytest.raises(BodyError):
        for snum, section in real_series.enumerateSections():
            raise BodyError  # loadSection on a corrupt file looks like this

    assert all(r.finished for r in recording.instances)


def test_natural_exhaustion_still_closes_it(real_series, recording):
    count = sum(1 for _ in real_series.enumerateSections())

    assert count == len(real_series.sections)
    assert all(r.finished for r in recording.instances)


def test_a_failed_open_still_closes_its_dialog(series_jser, monkeypatch):
    """openJser's finally: the reporter finishes even when the open raises.

    The failure is planted inside the extraction loop -- Section.updateJSON,
    which runs per section AFTER the reporter is built -- standing in for
    corrupt section data or an OSError mid-write.
    """
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.datatypes.section import Section

    class MidOpenError(Exception):
        pass

    def explode(*args, **kwargs):
        raise MidOpenError

    monkeypatch.setattr(Section, "updateJSON", staticmethod(explode))

    RecordingReporter.instances = []
    with pytest.raises(MidOpenError):
        Series.openJser(str(series_jser), progress=RecordingReporter)

    assert RecordingReporter.instances, "the reporter was never built"
    assert all(r.finished for r in RecordingReporter.instances)


def test_the_3d_worker_opens_series_without_qt(series_jser, monkeypatch):
    """generateVolumes(fp) must never reach the Qt reporter or notifier.

    It runs in the worker thread, where building a QProgressDialog is
    forbidden and crashed intermittently. The scene request is empty, which
    also pins the empty-extremes guard: every object gone is a valid scene.
    """
    from PyReconstruct.modules.backend.volume import generate_volumes as gv
    from PyReconstruct.modules.datatypes import series as series_module

    def qt_forbidden(*args, **kwargs):
        raise AssertionError("the worker reached the Qt default")

    monkeypatch.setattr(
        series_module, "_default_progress_reporter_factory", qt_forbidden
    )
    monkeypatch.setattr(series_module, "_default_notifier", qt_forbidden)

    meshes, series = gv.generateVolumes(
        str(series_jser),
        [{"name": "an_object_deleted_since_the_scene_was_saved"}],
        [],
    )
    try:
        assert meshes == []
    finally:
        series.close()

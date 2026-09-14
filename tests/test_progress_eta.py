"""Progress dialogs say how long is left.

His ask (2026-09-14), from recoloring every object in a series: the bar
showed a percentage but no time. The estimate lives in the GUI-free
ProgressReporter base, so every operation that reports progress gets it,
and QtProgressReporter puts it on the dialog's label once the job has run
long enough to say anything true.
"""
import types

from PyReconstruct.modules.backend.progress import (
    ETA_MIN_ELAPSED, ETA_MIN_PERCENT, NullProgressReporter, ProgressReporter,
    QtProgressReporter, estimate_remaining, format_remaining,
)


def test_no_estimate_until_enough_has_run():
    assert estimate_remaining(elapsed=1.0, percent=50) is None      # too soon
    assert estimate_remaining(elapsed=30.0, percent=2) is None      # too little done
    assert estimate_remaining(elapsed=30.0, percent=100) is None    # finished


def test_estimate_assumes_the_rate_so_far_holds():
    assert estimate_remaining(elapsed=10.0, percent=25) == 30.0
    assert estimate_remaining(elapsed=60.0, percent=50) == 60.0


def test_phrases_round_to_what_a_person_would_say():
    assert format_remaining(3) == "about 5 seconds left"
    assert format_remaining(42) == "about 40 seconds left"
    assert format_remaining(90) == "about 2 minutes left"
    assert format_remaining(60) == "about 1 minute left"
    assert format_remaining(3600) == "about 1 hour left"
    assert format_remaining(5400) == "about 1 h 30 min left"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Recording(ProgressReporter):
    def set_progress(self, percent):
        self.note_progress(percent)

    def was_canceled(self):
        return False


def test_reporter_eta_appears_only_after_the_thresholds():
    r = Recording("Recoloring")
    clock = FakeClock(); r._clock = clock
    r.set_progress(0)
    assert r.eta_text() is None
    clock.now += ETA_MIN_ELAPSED - 0.5
    r.set_progress(ETA_MIN_PERCENT + 5)
    assert r.eta_text() is None                     # enough done, too soon
    clock.now += 8.5                                # 10 s in, 10 percent done
    r.set_progress(10)
    assert r.eta_text() == "about 2 minutes left"   # 90 s more at that rate


def test_qt_reporter_writes_the_estimate_on_the_label(monkeypatch):
    calls = []
    fake_bar = types.SimpleNamespace(
        setValue=lambda v: calls.append(("value", v)),
        setLabelText=lambda t: calls.append(("label", t)),
        wasCanceled=lambda: False,
    )
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.utils.getProgbar", lambda text, cancel: fake_bar
    )
    r = QtProgressReporter("Recoloring 40 objects")
    clock = FakeClock(); r._clock = clock
    r.set_progress(0)
    clock.now += 20
    r.set_progress(50)
    labels = [t for kind, t in calls if kind == "label"]
    assert labels == ["Recoloring 40 objects\nabout 20 seconds left"]
    assert ("value", 50) in calls


def test_text_mode_bar_without_a_label_is_left_alone(monkeypatch):
    fake_bar = types.SimpleNamespace(setValue=lambda v: None, wasCanceled=lambda: False)
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.utils.getProgbar", lambda text, cancel: fake_bar
    )
    r = QtProgressReporter("Saving")
    clock = FakeClock(); r._clock = clock
    r.set_progress(0); clock.now += 20; r.set_progress(50)   # must not raise


def test_null_reporter_still_reports_nothing():
    r = NullProgressReporter("x")
    r.set_progress(50)
    assert r.eta_text() is None

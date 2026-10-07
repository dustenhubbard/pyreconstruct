"""Two save guards that no other test drives to their failure case.

``_atomicWrite`` opens its ``.save-<6 hex>.tmp`` temp file exclusively and, when
the name is already taken, picks another. The names come from
``secrets.token_hex``, so the tests here replace it with a fixed list to make
the collision happen every time.

``Series.saveJser`` sets a flag while it runs and refuses a second save while
the flag is up. The flag is cleared in a ``finally``, so a save that fails must
leave it down, or every later save of the series is refused.
"""

import errno
import os
import shutil
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_mod
from PyReconstruct.modules.datatypes.series import SeriesSaveError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "dev", "assets", "checker", "files", "shapes1.jser")

TAKEN = "c0111d"


def fixed_temp_names(monkeypatch, names):
    """Make ``_atomicWrite`` draw its temp names from `names`, in order."""
    names = iter(names)
    drawn = []

    def token_hex(nbytes):
        assert nbytes == 3
        drawn.append(next(names))
        return drawn[-1]

    monkeypatch.setattr(series_mod, "secrets", SimpleNamespace(token_hex=token_hex))
    return drawn


def leave_temp_file(folder, contents):
    """A temp file another write is still using, under the name `TAKEN`."""
    fp = os.path.join(folder, f".save-{TAKEN}.tmp")
    with open(fp, "wb") as f:
        f.write(contents)
    return fp


class RecordingNotifier(NullNotifier):
    def __init__(self):
        self.errors = []

    def notify_error(self, message, report):
        self.errors.append(message)
        return True


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def series(tmp_path, notifier):
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / os.path.basename(FIXTURE))
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(notifier)
    yield series
    series.leave_open = False
    series.close()


# --------------------------------------------------------------------------
# a temp name that is already taken
# --------------------------------------------------------------------------

def test_a_taken_temp_name_is_skipped_and_the_other_file_is_left_alone(
        tmp_path, monkeypatch):
    fp = str(tmp_path / "target.jser")
    with open(fp, "wb") as f:
        f.write(b"old")
    other = leave_temp_file(str(tmp_path), b"another write")
    drawn = fixed_temp_names(monkeypatch, [TAKEN, TAKEN, "0f1e2d"])

    series_mod._atomicWrite(fp, b"new")

    assert drawn == [TAKEN, TAKEN, "0f1e2d"]
    assert open(fp, "rb").read() == b"new"
    assert open(other, "rb").read() == b"another write"
    assert sorted(os.listdir(tmp_path)) == sorted(
        [os.path.basename(fp), os.path.basename(other)]
    )


def test_a_save_whose_first_temp_name_is_taken_still_writes_the_file(
        series, notifier, monkeypatch):
    """Both writes in a save, the .ser and the .jser, meet a taken name first."""
    series.saveJser()
    good = open(series.jser_fp, "rb").read()
    with open(series.jser_fp, "wb") as f:
        f.write(b"stale")

    others = [
        leave_temp_file(os.path.dirname(series.jser_fp), b"another write"),
        leave_temp_file(series.hidden_dir, b"another write"),
    ]
    drawn = fixed_temp_names(
        monkeypatch, [TAKEN, "000001", TAKEN, "000002"]
    )

    series.saveJser()

    assert drawn == [TAKEN, "000001", TAKEN, "000002"]
    assert open(series.jser_fp, "rb").read() == good
    for other in others:
        assert open(other, "rb").read() == b"another write"
    assert notifier.errors == []


# --------------------------------------------------------------------------
# a failed save does not leave the series marked as saving
# --------------------------------------------------------------------------

class Stop(BaseException):
    """Not an Exception, as a KeyboardInterrupt is not."""


def unreadable_last_section(series, monkeypatch):
    fp = os.path.join(series.hidden_dir, series.sections[max(series.sections)])
    good = open(fp, "rb").read()
    with open(fp, "wb") as f:
        f.write(b"{not json")

    def undo():
        with open(fp, "wb") as f:
            f.write(good)
    return SeriesSaveError, undo


def replace_fails(series, monkeypatch):
    real_replace = os.replace

    def failing_replace(src, dst):
        if dst == series.jser_fp:
            raise OSError(errno.EROFS, "Read-only file system")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    return OSError, monkeypatch.undo


def interrupted(series, monkeypatch):
    stopping = {"on": True}
    real_set_progress = Recording.set_progress

    def set_progress(self, percent):
        real_set_progress(self, percent)
        if stopping["on"]:
            raise Stop()

    monkeypatch.setattr(Recording, "set_progress", set_progress)
    return Stop, lambda: stopping.update(on=False)


class Recording(NullProgressReporter):
    """Notes whether the series said it was saving at each progress step."""
    series = None
    seen = []

    def set_progress(self, percent):
        Recording.seen.append(Recording.series.jserSaveRunning())


@pytest.mark.parametrize(
    "fail", [unreadable_last_section, replace_fails, interrupted],
    ids=["unreadable-section", "replace-fails", "interrupted"],
)
def test_a_failed_save_clears_the_saving_flag(series, notifier, monkeypatch, fail):
    series.saveJser()
    good = open(series.jser_fp, "rb").read()
    Recording.series, Recording.seen = series, []
    series.setProgressReporter(Recording)
    error, undo = fail(series, monkeypatch)

    with pytest.raises(error):
        series.saveJser()

    assert Recording.seen and all(Recording.seen), "the save never set the flag"
    assert series.jserSaveRunning() is False
    assert open(series.jser_fp, "rb").read() == good

    # the next save is not refused as a save inside a save
    undo()
    notifier.errors.clear()
    with open(series.jser_fp, "wb") as f:
        f.write(b"stale")
    series.saveJser()
    assert open(series.jser_fp, "rb").read() == good
    assert notifier.errors == []
    assert series.jserSaveRunning() is False

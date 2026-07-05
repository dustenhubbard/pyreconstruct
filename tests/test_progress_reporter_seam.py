"""Tests for the ProgressReporter seam (M11 PR 2).

Long-running `Series` operations report progress and honor cancellation through
a `ProgressReporter` instead of creating a Qt progress bar (`getProgbar`)
directly. These tests prove the seam:

  - `NullProgressReporter` is a pure-Python no-op that never cancels, and the
    reporter interface (set_progress / was_canceled / finish / context manager)
    behaves as documented;
  - the progress seam module works with NO Qt involved (verified in a subprocess
    where any `PySide6` import is blocked), while the `QtProgressReporter`
    adapter is the only piece that requires Qt;
  - `Series` operations route through an injected reporter factory: a canceling
    reporter aborts `openJser` mid-loop (returning None and cleaning up), and
    `enumerateSections` drives an injected reporter over every section;
  - opening/cancellation drives through the seam without importing the GUI layer
    (verified in a subprocess where `PyReconstruct.modules.gui` is blocked) --
    the payoff of moving `getProgbar` out of `series.py`.

Note: importing `Series` still pulls in Qt via `transform.py`'s `QTransform`
(out of scope for M11, deferred), so a full Series operation cannot yet run
under a total `PySide6` block; the GUI-layer block is the achievable headless
proof for progress and previews the PR 3 "cut the cord" headless test.
"""
import os
import sys
import shutil
import subprocess

import pytest

from PyReconstruct.modules.backend.progress import (
    ProgressReporter, NullProgressReporter
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


class _CancelingReporter(ProgressReporter):
    """A reporter that always reports cancellation (drives the abort path)."""

    def set_progress(self, percent):
        pass

    def was_canceled(self):
        return True


def test_null_reporter_basics():
    """NullProgressReporter drops progress, never cancels, and context-manages."""
    reporter = NullProgressReporter(text="working...", cancel=False)
    assert reporter.text == "working..."
    assert reporter.cancel is False
    assert reporter.was_canceled() is False
    # set_progress and finish are no-ops that must not raise
    reporter.set_progress(42)
    reporter.finish()
    # context-manager friendly: finalizes on clean exit, still never cancels
    with NullProgressReporter() as r:
        r.set_progress(50)
        assert r.was_canceled() is False


def test_progress_seam_needs_no_qt():
    """The seam is Qt-free: NullProgressReporter drives a loop with PySide6 blocked.

    Runs in a subprocess that makes any `PySide6` import raise, then imports the
    progress module and drives a loop through NullProgressReporter. Confirms Qt
    is never pulled in and that QtProgressReporter is the only piece needing it.
    """
    script = r"""
import sys

# drop any pre-loaded PySide6 (e.g. a dev-env sitecustomize) so the block
# governs the (re)import and this is a genuine proof in any environment
for _m in list(sys.modules):
    if _m == "PySide6" or _m.startswith("PySide6."):
        del sys.modules[_m]

class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 blocked for headless proof")
        return None

sys.meta_path.insert(0, _BlockPySide6())

from PyReconstruct.modules.backend.progress import (
    ProgressReporter, NullProgressReporter, QtProgressReporter
)

# drive a progress loop with cancellation checks through the no-op reporter
reporter = NullProgressReporter(text="headless", cancel=False)
seen = []
for i in range(5):
    if reporter.was_canceled():
        break
    reporter.set_progress(i / 5 * 100)
    seen.append(i)
reporter.finish()
assert seen == [0, 1, 2, 3, 4]
assert reporter.was_canceled() is False

# no Qt was imported to build/use the pure-Python reporter
assert "PySide6" not in sys.modules
assert "PySide6.QtWidgets" not in sys.modules

# the Qt adapter is the sole piece that needs Qt: it must fail fast when blocked
try:
    QtProgressReporter(text="x")
except ImportError:
    pass
else:
    raise AssertionError("QtProgressReporter should require PySide6")

print("HEADLESS_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "HEADLESS_OK" in result.stdout


def test_openJser_honors_cancellation(tmp_path):
    """A canceling reporter aborts openJser mid-loop: None + hidden dir cleaned."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PyReconstruct.modules.datatypes.series import Series

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    hidden_dir = str(tmp_path / ".shapes1")

    # a reporter reporting canceled=True must abort the load and leave no
    # partial hidden dir behind (the cancellation contract getProgbar had)
    result = Series.openJser(fp, progress=_CancelingReporter)
    assert result is None
    assert not os.path.isdir(hidden_dir)

    # control: a never-canceling reporter opens the same fixture successfully
    result = Series.openJser(fp, progress=NullProgressReporter)
    assert result is not None
    result.close()


def test_enumerateSections_routes_through_injected_reporter(tmp_path):
    """enumerateSections drives the injected reporter over every section."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PyReconstruct.modules.datatypes.series import Series

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    series = Series.openJser(fp, progress=NullProgressReporter)

    # record every reporter interaction to prove the loop drives our factory
    calls = []

    class _RecordingReporter(ProgressReporter):
        def set_progress(self, percent):
            calls.append(percent)

        def was_canceled(self):
            return False

    series.setProgressReporter(_RecordingReporter)
    assert series._progressReporterFactory() is _RecordingReporter

    # default show_progress=True, so the SeriesIterator drives the reporter
    snums = [snum for snum, _ in series.enumerateSections(message="Loading...")]
    series.close()

    assert snums == sorted(series.sections.keys())
    # the iterator reports progress once per section plus a final update
    assert calls, "reporter was never driven by enumerateSections"
    assert calls[-1] == 100  # finalized to 100% on StopIteration


def test_progress_path_needs_no_gui_layer(tmp_path):
    """openJser + cancellation drive through the seam without the GUI layer.

    Importing `Series` still needs PySide6 (via transform.py's QTransform, out
    of M11 scope), so this blocks `PyReconstruct.modules.gui` -- the getProgbar
    home -- rather than PySide6 entirely. It proves the progress path no longer
    reaches into the GUI layer, the point of this seam, and previews PR 3.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    script = r"""
import sys, os

class _BlockGui:
    def find_spec(self, name, path=None, target=None):
        if name == "PyReconstruct.modules.gui" or name.startswith(
            "PyReconstruct.modules.gui."
        ):
            raise ImportError("GUI layer blocked for headless progress proof")
        return None

sys.meta_path.insert(0, _BlockGui())

from PyReconstruct.modules.backend.progress import ProgressReporter
from PyReconstruct.modules.datatypes.series import Series

class _Cancel(ProgressReporter):
    def set_progress(self, percent):
        pass
    def was_canceled(self):
        return True

fp = sys.argv[1]
hidden_dir = os.path.join(os.path.dirname(fp), ".shapes1")

result = Series.openJser(fp, progress=_Cancel)
assert result is None, "cancellation did not abort the load"
assert not os.path.isdir(hidden_dir), "partial hidden dir left after cancel"

# the GUI layer (getProgbar's home) was never imported to open/cancel
assert not any(
    m == "PyReconstruct.modules.gui" or m.startswith("PyReconstruct.modules.gui.")
    for m in sys.modules
), "opening/cancelling pulled in the GUI layer"

print("GUI_FREE_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script, fp],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "GUI_FREE_OK" in result.stdout

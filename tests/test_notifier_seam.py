"""Tests for the Notifier seam (M11 PR 3 -- "cut the cord").

`Series` surfaces user-facing messages (e.g. a failed-save warning) through a
`Notifier` instead of importing the GUI `notify` helper (and `QApplication` /
`qt_offscreen`) directly. This is the final seam of M11: after it, `series.py`
imports nothing from `PyReconstruct.modules.gui`. These tests prove it:

  - `NullNotifier` is a pure-Python no-op that never notifies (returns False so
    a caller can fall back to its own reporting);
  - the notifier module works with NO Qt involved (verified in a subprocess
    where any `PySide6` import is blocked), while the `QtNotifier` adapter is
    the only piece that requires Qt/GUI;
  - `Series._surfaceSaveError` routes through the injected notifier, printing
    its fallback message only when the notifier reports it did not surface one;
  - the capstone: with `PyReconstruct.modules.gui` import forbidden, `Series`
    still imports and its notify path runs through a `NullNotifier` without ever
    pulling in the GUI layer, while `QtNotifier` is confirmed to be the sole
    piece that needs it -- proving `Series` no longer depends on `gui/`;
  - a source-level (AST) check asserts `series.py` has no
    `PyReconstruct.modules.gui` import.

Note: importing `Series` still pulls in Qt via `transform.py`'s `QTransform`
(deferred, out of M11 scope), so a full `Series` import cannot yet run under a
total `PySide6` block; the block here is on `PyReconstruct.modules.gui`, not all
of `PySide6`, which is the achievable headless proof and the payoff of M11.
"""
import os
import sys
import ast
import subprocess

from PyReconstruct.modules.backend.notifier import Notifier, NullNotifier

SERIES_SRC = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "modules", "datatypes", "series.py",
)


def test_null_notifier_basics():
    """NullNotifier never notifies and returns False (fall-back signal)."""
    notifier = NullNotifier()
    assert notifier.notify("anything") is False


def test_notifier_seam_needs_no_qt():
    """The seam is Qt-free: NullNotifier notifies with PySide6 blocked.

    Runs in a subprocess that makes any `PySide6` import raise, then imports the
    notifier module and uses NullNotifier. Confirms Qt is never pulled in and
    that the QtNotifier adapter is the only piece that requires it.
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

from PyReconstruct.modules.backend.notifier import (
    Notifier, NullNotifier, QtNotifier
)

# the pure-Python notifier surfaces nothing and needs no Qt
assert NullNotifier().notify("headless") is False

# no Qt was imported to build/use the pure-Python notifier
assert "PySide6" not in sys.modules
assert "PySide6.QtWidgets" not in sys.modules

# the Qt adapter is the sole piece that needs Qt: it must fail fast when blocked
try:
    QtNotifier().notify("x")
except ImportError:
    pass
else:
    raise AssertionError("QtNotifier should require PySide6/GUI")

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


def test_surface_save_error_routes_through_injected_notifier(capsys):
    """_surfaceSaveError calls the injected notifier and prints only on a miss."""
    from PyReconstruct.modules.datatypes.series import Series

    seen = []

    class _RecordingNotifier(Notifier):
        def __init__(self, surfaced):
            self._surfaced = surfaced

        def notify(self, message):
            seen.append(message)
            return self._surfaced

    # a notifier that surfaces the message: no fallback print
    series = Series.__new__(Series)
    series.setNotifier(_RecordingNotifier(surfaced=True))
    assert isinstance(series._notifier(), _RecordingNotifier)

    series._surfaceSaveError("/tmp/x.jser", OSError("disk full"))
    assert len(seen) == 1
    assert "Save failed: disk full" in seen[0]
    assert "/tmp/x.jser" in seen[0]
    assert capsys.readouterr().out == ""  # surfaced -> nothing printed

    # a notifier that reports it did not surface: fallback prints the message
    series.setNotifier(_RecordingNotifier(surfaced=False))
    series._surfaceSaveError("/tmp/y.jser", OSError("boom"))
    assert len(seen) == 2
    printed = capsys.readouterr().out
    assert "Save failed: boom" in printed
    assert "/tmp/y.jser" in printed


def test_notifier_exception_never_masks_the_error(capsys):
    """A broken notifier is swallowed and the fallback message still prints."""
    from PyReconstruct.modules.datatypes.series import Series

    class _BrokenNotifier(Notifier):
        def notify(self, message):
            raise RuntimeError("notifier exploded")

    series = Series.__new__(Series)
    series.setNotifier(_BrokenNotifier())
    # must not raise: the notification failure is swallowed, message still shown
    series._surfaceSaveError("/tmp/z.jser", OSError("nope"))
    printed = capsys.readouterr().out
    assert "Save failed: nope" in printed
    assert "/tmp/z.jser" in printed


def test_series_notify_path_needs_no_gui_layer():
    """Capstone: Series' notify path runs with `modules.gui` import forbidden.

    Importing `Series` still needs PySide6 (via transform.py's QTransform, out of
    M11 scope), so this blocks `PyReconstruct.modules.gui` -- the `notify`
    helper's home -- rather than PySide6 entirely. It proves `Series` no longer
    reaches into the GUI layer: the notify path runs through an injected
    NullNotifier without importing `gui/`, while QtNotifier is confirmed to be
    the only piece that needs it. This is the payoff of M11 PR 3.
    """
    script = r"""
import sys

# drop any pre-imported PyReconstruct modules (e.g. a dev-env sitecustomize
# that imports Series at startup) so Series is re-imported fresh under the
# block -- otherwise a cached import would bypass the proof
for _m in list(sys.modules):
    if _m.startswith("PyReconstruct"):
        del sys.modules[_m]

class _BlockGui:
    def find_spec(self, name, path=None, target=None):
        if name == "PyReconstruct.modules.gui" or name.startswith(
            "PyReconstruct.modules.gui."
        ):
            raise ImportError("GUI layer blocked for headless notify proof")
        return None

sys.meta_path.insert(0, _BlockGui())

from PyReconstruct.modules.backend.notifier import NullNotifier, QtNotifier
from PyReconstruct.modules.datatypes.series import Series

# importing Series must not have pulled in the GUI layer
assert not any(
    m == "PyReconstruct.modules.gui" or m.startswith("PyReconstruct.modules.gui.")
    for m in sys.modules
), "importing Series pulled in the GUI layer"

# the notify path runs end-to-end through a Qt/GUI-free NullNotifier
series = Series.__new__(Series)
series.setNotifier(NullNotifier())
series._surfaceSaveError("/tmp/headless.jser", OSError("headless disk full"))

# still no GUI layer after exercising the notify path
assert not any(
    m == "PyReconstruct.modules.gui" or m.startswith("PyReconstruct.modules.gui.")
    for m in sys.modules
), "the notify path pulled in the GUI layer"

# QtNotifier is the sole piece that needs the GUI layer: it must fail when blocked
try:
    QtNotifier().notify("x")
except ImportError:
    pass
else:
    raise AssertionError("QtNotifier should require the GUI layer")

print("GUI_FREE_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "GUI_FREE_OK" in result.stdout


def test_series_source_has_no_gui_import():
    """series.py must not import anything from PyReconstruct.modules.gui.

    Parses the source (so lazy, function-level imports are caught too) and walks
    every import node. Docstrings that mention the GUI are fine; import
    statements referencing `PyReconstruct.modules.gui` are not.
    """
    with open(SERIES_SRC, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "PyReconstruct.modules.gui" or mod.startswith(
                "PyReconstruct.modules.gui."
            ):
                offenders.append(f"line {node.lineno}: from {mod} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "PyReconstruct.modules.gui" or alias.name.startswith(
                    "PyReconstruct.modules.gui."
                ):
                    offenders.append(f"line {node.lineno}: import {alias.name}")

    assert not offenders, "series.py imports the GUI layer:\n" + "\n".join(offenders)

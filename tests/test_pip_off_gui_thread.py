"""pip installs must not freeze the window.

install_module used to run pip with a bare subprocess.run on the GUI
thread: minutes of "Not Responding" for a heavy package. With a user
present, _run_pip now hands pip to a worker thread and holds the screen
with a busy bar in a local event loop; with nobody present it IS
subprocess.run, so scripts, tests, and the offscreen platform keep the
exact old path (and the old stubbing seam).
"""

import subprocess
import threading

import pytest

from PyReconstruct.modules.backend.imports import mod_imports
from PyReconstruct.modules.gui.utils import utils as gui_utils

pytestmark = pytest.mark.gui


def test_headless_callers_keep_the_plain_path(monkeypatch):
    """user_is_present is False here, so no Qt machinery is touched."""
    assert gui_utils.user_is_present() is False

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["thread"] = threading.get_ident()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod_imports.subprocess, "run", fake_run)

    result = mod_imports._run_pip(["python", "-m", "pip", "install", "x"])

    assert result.returncode == 0
    assert seen["thread"] == threading.get_ident()   # same thread: no worker


def test_with_a_user_pip_runs_off_the_gui_thread(qapp, monkeypatch):
    """The worker path: pip's blocking wait happens on ANOTHER thread while
    the GUI thread sits in a local event loop behind a busy bar."""
    progbars = []

    class RecordingProgbar:
        def __init__(self):
            self.closed = False
            progbars.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(gui_utils, "user_is_present", lambda: True)
    monkeypatch.setattr(
        gui_utils, "getProgbar", lambda *a, **k: RecordingProgbar()
    )

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["thread"] = threading.get_ident()
        return subprocess.CompletedProcess(cmd, 0, "installed", "")

    monkeypatch.setattr(mod_imports.subprocess, "run", fake_run)

    result = mod_imports._run_pip(["python", "-m", "pip", "install", "x"])

    assert result.stdout == "installed"
    assert seen["thread"] != threading.get_ident(), (
        "pip blocked the GUI thread"
    )
    assert progbars and progbars[0].closed, "the busy bar never came down"


def test_a_worker_failure_reaches_the_caller(qapp, monkeypatch):
    monkeypatch.setattr(gui_utils, "user_is_present", lambda: True)

    class NullProgbar:
        def close(self):
            pass

    monkeypatch.setattr(gui_utils, "getProgbar", lambda *a, **k: NullProgbar())

    def exploding_run(cmd, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(mod_imports.subprocess, "run", exploding_run)

    with pytest.raises(OSError, match="no network"):
        mod_imports._run_pip(["python", "-m", "pip", "install", "x"])

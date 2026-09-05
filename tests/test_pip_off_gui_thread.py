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


@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_install_shows_a_modal_dialog_until_worker_finishes(
    qapp, qtbot, monkeypatch, fails
):
    """Check the real dialog during the wait, including error-path teardown."""
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QProgressDialog, QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(gui_utils, "mainwindow", parent)
    monkeypatch.setattr(gui_utils, "user_is_present", lambda: True)

    release_worker = threading.Event()
    worker_threads = []
    observed = {}

    def fake_run(cmd, **kwargs):
        worker_threads.append(threading.get_ident())
        if not release_worker.wait(timeout=5):
            raise TimeoutError("the GUI timer did not release the pip worker")
        if fails:
            raise OSError("test install failed")
        return subprocess.CompletedProcess(cmd, 0, "installed", "")

    def inspect_dialog():
        try:
            dialog = parent.findChild(QProgressDialog)
            observed["dialog"] = dialog
            if dialog is not None:
                observed["visible"] = dialog.isVisible()
                observed["modal"] = qapp.activeModalWidget() is dialog
                observed["modality"] = dialog.windowModality()
                observed["range"] = (dialog.minimum(), dialog.maximum())
        finally:
            release_worker.set()

    monkeypatch.setattr(mod_imports.subprocess, "run", fake_run)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(inspect_dialog)
    timer.start(50)

    cmd = ["python", "-m", "pip", "install", "x"]
    if fails:
        with pytest.raises(OSError, match="test install failed"):
            mod_imports._run_pip(cmd)
    else:
        assert mod_imports._run_pip(cmd).stdout == "installed"

    assert worker_threads and worker_threads[0] != threading.get_ident()
    assert observed.get("visible"), "the install progress dialog was never shown"
    assert observed["modal"], "the parent window remained interactive during install"
    assert observed["modality"] == Qt.ApplicationModal
    assert observed["range"] == (0, 0)
    assert not observed["dialog"].isVisible()
    assert qapp.activeModalWidget() is None


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

"""The .jser file association, app half and installer half.

Double-clicking a .jser reaches the app three different ways:

* Windows and Linux pass the path as argv; the CLI already handles that
  (``cli.py``, positional path). The installers had no association, so
  nothing ever invoked it. The Inno script now registers the extension and
  the Linux installer ships a MIME type for the existing ``Exec ... %f``.
* macOS never uses argv: LaunchServices delivers a QFileOpenEvent, at launch
  or while running. ``run.FileOpenWatcher`` is the app half; the bundle's
  CFBundleDocumentTypes claim is the installer half.

The watcher tests drive the real event through the real filter. The
installer-side tests are content guards: CI cannot run Inno Setup or a
desktop environment, but it can refuse a refactor that silently drops the
association lines these features live in.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# the macOS app half: FileOpenWatcher
# --------------------------------------------------------------------------

def _send_open(qapp, watcher, path):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent

    return qapp.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile(path)))


@pytest.fixture
def watcher(qapp):
    from PyReconstruct.run import FileOpenWatcher

    w = FileOpenWatcher()
    qapp.installEventFilter(w)
    yield w
    qapp.removeEventFilter(w)


def test_open_before_the_window_parks_the_path(qapp, watcher):
    """A launch-time double-click arrives before MainWindow exists; the path
    waits in ``pending`` for runPyReconstruct to collect."""
    _send_open(qapp, watcher, "/somewhere/series.jser")
    assert watcher.pending == "/somewhere/series.jser"


def test_open_with_a_window_opens_the_series(qapp, watcher):
    """A double-click while the app runs goes straight into the live window."""
    opened = []

    class Window:
        def openSeries(self, series_obj=None, jser_fp=None, query_prev=True):
            opened.append(jser_fp)

    watcher.main_window = Window()
    _send_open(qapp, watcher, "/somewhere/else.jser")
    assert opened == ["/somewhere/else.jser"]
    assert watcher.pending is None


def test_other_events_pass_through(qapp, watcher):
    """The filter claims FileOpen and nothing else."""
    from PySide6.QtCore import QEvent

    class Probe:
        pass

    # a plain event is not intercepted: eventFilter returns falsy for it
    assert watcher.eventFilter(qapp, QEvent(QEvent.Type.User)) is False


def test_empty_file_events_are_ignored(qapp, watcher):
    """macOS can deliver a FileOpen carrying a URL only; an empty file string
    must not become a pending 'open nothing'."""
    from PySide6.QtGui import QFileOpenEvent
    from PySide6.QtCore import QUrl

    qapp.sendEvent(qapp, QFileOpenEvent(QUrl("https://example.test/not-a-file")))
    assert watcher.pending is None


# --------------------------------------------------------------------------
# installer halves: content guards
# --------------------------------------------------------------------------

def test_windows_installer_registers_the_extension():
    iss = (REPO / "packaging/windows/PyReconstruct.iss").read_text(encoding="utf-8")
    assert "ChangesAssociations=yes" in iss
    assert 'Subkey: "Software\\Classes\\.jser' in iss
    assert "shell\\open\\command" in iss
    # both flavors carry their own ProgID so stable and Dev can coexist
    assert 'PYR_PROGID "PyReconstruct.jser"' in iss
    assert 'PYR_PROGID "PyReconstructDev.jser"' in iss


def test_macos_bundle_claims_the_extension():
    spec = (REPO / "packaging/PyReconstruct.spec").read_text(encoding="utf-8")
    assert "CFBundleDocumentTypes" in spec
    assert "UTExportedTypeDeclarations" in spec
    assert '"public.filename-extension": ["jser"]' in spec


def test_linux_desktop_entry_declares_the_mime_type():
    desktop = (REPO / "packaging/linux/pyreconstruct.desktop.in").read_text(encoding="utf-8")
    assert "MimeType=application/x-pyreconstruct-jser;" in desktop
    assert "%f" in desktop  # the file argument the association hands over
    mime = (REPO / "packaging/linux/pyreconstruct-mime.xml").read_text(encoding="utf-8")
    assert 'pattern="*.jser"' in mime
    install = (REPO / "packaging/linux/install.sh").read_text(encoding="utf-8")
    assert "install_mime" in install
    assert "update-mime-database" in install
    uninstall = (REPO / "packaging/linux/uninstall.sh").read_text(encoding="utf-8")
    assert "pyreconstruct.xml" in uninstall

"""A single, polished dialog for the in-app updater.

Shows the available version, channel, download size, and the release notes
("What's new"), then runs the download + checksum verify inline (progress bar +
status) and hands the verified installer to the main window for the
launch-on-close step. Styling is intentionally plain Qt so it inherits the app
theme.
"""
import threading
import tempfile
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QProgressBar,
    QPushButton, QWidget,
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt

from PyReconstruct.modules.backend.threading import ThreadPool
from PyReconstruct.modules.backend.updater.updater import (
    download_asset, fetch_checksum, UpdateCancelled,
)


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _space_after_headings(browser, extra=10):
    """Add breathing room below markdown headings in a notes browser.

    Qt's ``setMarkdown`` ignores the document default stylesheet, so we walk the
    blocks and bump the bottom margin on heading blocks instead. Applies to
    whatever headings the notes carry.
    """
    doc = browser.document()
    cursor = QTextCursor(doc)
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        if fmt.headingLevel() > 0:
            fmt.setBottomMargin(fmt.bottomMargin() + extra)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(fmt)
        block = block.next()


def make_notes_browser(markdown_text, min_height=180):
    """Build a read-only ``QTextBrowser`` that renders release-note markdown.

    Shared by the updater dialog and the first-launch "What's new" dialog so both
    render notes identically (markdown view, external links, heading spacing).
    Falls back to plain text if the markdown can't be rendered.
    """
    text = markdown_text or "_No release notes were published._"
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    try:
        browser.setMarkdown(text)
        _space_after_headings(browser)
    except Exception:
        browser.setPlainText(text)
    browser.setMinimumHeight(min_height)
    return browser


class UpdateDialog(QDialog):
    """Presents an available update and performs the download/verify in place.

    On success it sets ``parent._pending_installer`` / ``_pending_update_dir`` and
    accepts; the caller then closes the window so the existing closeEvent launches
    the installer. The dialog never launches anything itself.
    """

    def __init__(self, parent, info, channel):
        super().__init__(parent)
        self._parent = parent
        self._info = info
        self._asset = info["asset"]
        self._release = info["release"]
        self._channel = channel
        self._pool = None
        self._cancel = threading.Event()
        self._tmpdir = None

        self.setWindowTitle("PyReconstruct — Update")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)

        status = info["status"]
        remote, local = info["remote_version"], info["local_version"]
        head = {
            "newer": f"<b>Update available:</b> {remote}",
            "older": f"<b>Downgrade:</b> {self._channel} build is {remote}",
            "same": f"<b>Reinstall {remote}</b>",
            "unknown": f"<b>{self._channel} build:</b> {remote}",
        }.get(status, f"<b>{self._channel} build:</b> {remote}")
        self._headline = QLabel(head)
        lay.addWidget(self._headline)

        sub = f"You have {local}  ·  channel: {self._channel}  ·  download: {human_size(self._asset.get('size'))}"
        lay.addWidget(QLabel(sub))

        notes = (self._release or {}).get("body") or "_No release notes were published._"
        self._notes = make_notes_browser(notes)
        lay.addWidget(QLabel("<b>What's new</b>"))
        lay.addWidget(self._notes)

        # progress (hidden until download starts)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)
        self._status = QLabel("")
        self._status.setVisible(False)
        lay.addWidget(self._status)

        # buttons
        row = QHBoxLayout()
        row.addStretch(1)
        self._later_btn = QPushButton("Later")
        self._install_btn = QPushButton("Download && Install")
        self._install_btn.setDefault(True)
        self._later_btn.clicked.connect(self.reject)
        self._install_btn.clicked.connect(self._start_download)
        row.addWidget(self._later_btn)
        row.addWidget(self._install_btn)
        lay.addLayout(row)

    # --- download / verify ---------------------------------------------------
    def _start_download(self):
        self._install_btn.setEnabled(False)
        self._later_btn.setText("Cancel")
        self._progress.setVisible(True)
        self._status.setVisible(True)
        self._status.setText("Downloading…")

        name = self._asset["name"]
        url = self._asset["browser_download_url"]
        self._tmpdir = tempfile.mkdtemp(prefix="pyrecon-update-")  # 0700 by default
        dest = str(Path(self._tmpdir) / name)

        self._pool = ThreadPool()
        self._parent._updater_pool = self._pool  # in-flight guard

        def _job():
            sha = download_asset(url, dest,
                                 progress_cb=worker.signals.progress.emit,
                                 cancel_cb=self._cancel.is_set)
            cs_status, expected = fetch_checksum(self._release, name)
            return (sha, cs_status, expected, dest)

        worker = self._pool.createWorker(_job)
        worker.signals.progress.connect(lambda p: self._progress.setValue(min(p, 99)))
        worker.signals.result.connect(self._on_downloaded)
        worker.signals.error.connect(self._on_error)
        self._pool.start(worker)

    def _on_downloaded(self, result):
        from PyReconstruct.modules.gui.utils import notifyConfirm
        self._pool = None
        self._parent._updater_pool = None
        sha, cs_status, expected, dest = result

        # The user backed out (Esc/X/Cancel) while the last bytes were arriving,
        # or the dialog is otherwise gone: discard the download and never arm
        # the pending-installer hand-off.
        if self._cancel.is_set() or not self.isVisible():
            self._cleanup()
            self.reject()
            return

        self._status.setText("Verifying…")
        self._progress.setValue(100)

        if cs_status == "ok":
            if sha.lower() != expected.lower():
                self._fail("Verification failed (checksum mismatch). Nothing was installed.")
                return
        elif cs_status == "error":
            self._fail("Couldn't verify the download (checksum unreachable). Not installing — try again.")
            return
        else:  # missing
            from PyReconstruct.modules.backend.updater.install_info import install_kind
            if install_kind() == "frozen":
                # A frozen build must never offer to run an unverifiable
                # installer -- refuse outright and rely on the OS installer
                # signature checks for what did verify.
                self._fail("This download can't be verified (no checksum was published for it). Nothing was installed.")
                return
            if not notifyConfirm("The download couldn't be checksum-verified (none was published).\n\nInstall anyway?", yn=True):
                self._cleanup()
                self.reject()
                return

        # hand off to the window's launch-on-close path
        self._parent._pending_installer = dest
        self._parent._pending_update_dir = self._tmpdir
        self._tmpdir = None  # ownership transferred; don't clean it up here
        self.accept()

    def _on_error(self, err):
        self._pool = None
        self._parent._updater_pool = None
        exc = err[1] if isinstance(err, (tuple, list)) and len(err) >= 2 else err
        if isinstance(exc, UpdateCancelled):
            self._cleanup()
            self.reject()
            return
        self._fail(f"Download failed:\n{exc}")

    def _fail(self, msg):
        from PyReconstruct.modules.gui.utils import notify
        self._cleanup()
        notify(msg)
        self.reject()

    def reject(self):
        """Esc, the window X, and the Later/Cancel button all funnel here.

        While a download is in flight, don't dismiss yet: flag the cancel and let
        the worker unwind -- ``_on_error`` (UpdateCancelled) or ``_on_downloaded``
        (if the download won the race) re-enters ``reject()`` with no pool and
        closes for real. Dismissing immediately would leave the download running
        and later arm the pending-installer hand-off from a dialog the user
        already dismissed.
        """
        if self._pool is not None:
            self._cancel.set()
            self._status.setText("Cancelling…")
            return
        super().reject()

    def _cleanup(self):
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

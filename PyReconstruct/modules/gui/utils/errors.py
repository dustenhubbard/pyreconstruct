import os
import sys
import html
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)

from PyReconstruct.modules.constants import gh_issues

# Sibling module, relative like the package's own re-exports: an absolute import
# here would re-enter `gui.utils.__init__`, which is what imports this file.
from .confetti import burst_confetti

# Qt-free report builders (usable from the headless data model too).
from PyReconstruct.modules.backend.func.error_report import (
    build_error_report,
    build_diagnostic_report,
)


def _standard_summary(lead_html: str) -> str:
    """Wrap a lead line with the standard copy-and-report instructions + link."""
    return (
        f"{lead_html}<br><br>"
        "Click <b>Copy report to clipboard</b> below, then paste it into a bug "
        "report or email so we can help.<br><br>"
        f'Report bugs at <a href="{gh_issues}">{gh_issues}</a>'
    )


class ErrorReportDialog(QDialog):
    """Modal window that shows a copyable report.

    The frozen app has no console, so lay users cannot read the traceback that
    ``sys.__excepthook__`` prints to stderr. This shows the full report inline
    and a one-click "Copy report to clipboard" button so it can be pasted into a
    bug report or email.
    """

    def __init__(self, summary_html: str, report: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Error")
        self._report = report

        layout = QVBoxLayout(self)

        heading = QLabel(summary_html)
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.RichText)
        heading.setTextInteractionFlags(Qt.TextBrowserInteraction)
        heading.setOpenExternalLinks(True)
        layout.addWidget(heading)

        view = QPlainTextEdit(report)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.NoWrap)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        layout.addWidget(view)

        buttons = QHBoxLayout()
        self._copy_btn = QPushButton("Copy report to clipboard")
        self._copy_btn.clicked.connect(self._copyReport)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        buttons.addWidget(self._copy_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.resize(720, 480)

    def _copyReport(self):
        """Copy the report, confirm it in the button, and celebrate a little.

        The confetti fires only when there was a clipboard to write to. On a
        platform where ``QApplication.clipboard()`` returns None nothing was
        copied, and an animation that says otherwise is worse than no animation.

        The button text is set on both paths, which is what it did before this
        and is left alone deliberately: the label is the honest half of the
        feedback and its behavior is not what this change is about. (It is
        arguably wrong on the no-clipboard path. That is a separate question
        from whether to animate, and answering it here would hide a behavior
        change inside a decoration change.)

        The burst is wrapped because this dialog is the error handler. Every
        other failure path in this module is written so that the reporter cannot
        itself become the fault -- see ``show_error_report`` -- and a decoration
        that could raise out of a clicked handler would undo that for the sake
        of some dots. A copy that worked must not look like a copy that failed.
        """
        clipboard = QApplication.clipboard()
        copied = clipboard is not None
        if copied:
            clipboard.setText(self._report)
        self._copy_btn.setText("Copied ✓")
        if copied:
            try:
                burst_confetti(self._copy_btn)
            except Exception:
                pass


# True while a report dialog is running its own modal event loop. See
# show_error_report for why a report must never open from inside one.
_showing_report = False


def show_error_report(summary_html: str, report: str, parent=None, title="Error") -> bool:
    """Show ``report`` in a copyable dialog, never letting the display itself fail.

    Shared by the global exception hook, the handled save-error path, and the
    Help-menu diagnostics action. Falls back to a plain message box if the rich
    dialog cannot be constructed. Returns whether anything was actually put in
    front of the user, so a caller that keeps a record of what it has reported
    does not write one down for a report that never appeared.

    One dialog at a time, and that guard is load bearing rather than tidy.
    ``QDialog.exec`` runs its own event loop, which goes on delivering events to
    the rest of the app -- paint events among them, because the dialog appearing
    over a window exposes it. A widget whose ``paintEvent`` raises therefore
    reaches the exception hook again from *inside* this call, and without the
    guard opens a second dialog on top of the first, whose loop delivers the next
    paint event, and so on with nothing bounding it. That is the shape a user hit
    on 1.21.0: a field left with no section layer, an unstoppable stack of error
    windows, and PyReconstruct killed from Task Manager. The hook is not the only
    door: ``show_diagnostic_report`` and ``show_save_error`` arrive here without
    passing through ``customExcepthook``, so its deduplication cannot bound them
    and this guard is the only thing that does.

    A report suppressed here is not lost *when it came from the hook*:
    ``customExcepthook`` writes every occurrence to the log file before it gets
    this far, and ``Help > View log file`` reads it back. The other two callers
    do no logging of their own, so a report suppressed for them leaves no record
    -- reachable only from inside an open report window, which is application
    modal.
    """
    global _showing_report

    if _showing_report:
        return False

    active_window = QApplication.activeWindow()
    if parent is None:
        parent = active_window

    _showing_report = True
    try:
        try:
            dialog = ErrorReportDialog(summary_html, report, parent)
            dialog.setWindowTitle(title)
            dialog.exec()
        except Exception:
            # the error handler itself must never fail -- fall back to a plain box
            QMessageBox.critical(parent, title, f"{report}\n\n{gh_issues}", QMessageBox.Ok)
    finally:
        _showing_report = False

    if active_window:
        active_window.activateWindow()

    return True


def show_save_error(message: str, report: str, parent=None):
    """Copyable dialog for a handled save failure (used by the Notifier seam).

    ``message`` is the plain-text explanation already shown to the user; the
    ``report`` carries the traceback + environment for pasting into a bug report.
    """
    lead = html.escape(message).replace("\n", "<br>")
    show_error_report(_standard_summary(lead), report, parent, title="Save failed")


class LogViewerDialog(QDialog):
    """Read-only viewer for the app log file, with copy + open-folder buttons."""

    def __init__(self, log_text: str, log_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log file")
        self._text = log_text
        self._log_path = log_path

        layout = QVBoxLayout(self)

        heading = QLabel(f"Log file:<br><code>{html.escape(str(log_path))}</code>")
        heading.setTextFormat(Qt.RichText)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        view = QPlainTextEdit(log_text)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.NoWrap)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        view.moveCursor(QTextCursor.End)   # show the most recent output
        layout.addWidget(view)

        buttons = QHBoxLayout()
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.clicked.connect(self._copy)
        open_btn = QPushButton("Open log folder")
        open_btn.clicked.connect(self._openFolder)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        buttons.addWidget(self._copy_btn)
        buttons.addWidget(open_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.resize(820, 560)

    def _copy(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._text)
        self._copy_btn.setText("Copied ✓")

    def _openFolder(self):
        _open_log_folder(self._log_path)


def _open_log_folder(log_path):
    """Reveal the log's containing folder in the OS file manager (best-effort)."""
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl
    folder = os.path.dirname(str(log_path))
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def show_log_file(parent=None):
    """Help-menu action: view the log file's recent output in a copyable dialog."""
    from PyReconstruct.modules.backend.func.logging_setup import (
        read_log_tail,
        log_file_path,
    )
    text = read_log_tail()
    path = log_file_path()
    if parent is None:
        parent = QApplication.activeWindow()
    try:
        LogViewerDialog(text, path, parent).exec()
    except Exception:
        QMessageBox.information(parent, "Log file", f"Log file:\n{path}", QMessageBox.Ok)


def open_log_folder(parent=None):
    """Help-menu action: open the folder containing the log file."""
    from PyReconstruct.modules.backend.func.logging_setup import log_file_path
    _open_log_folder(log_file_path())


def show_diagnostic_report(parent=None):
    """Help-menu action: show a copyable version/OS report (no error required)."""
    report = build_diagnostic_report()
    lead = (
        "<b>Diagnostic report</b><br><br>"
        "These details (your PyReconstruct version and operating system) help us "
        "diagnose problems."
    )
    show_error_report(_standard_summary(lead), report, parent, title="Diagnostic report")


# Faults already reported in this session, by _error_signature. See
# customExcepthook for what this is for.
_reported_signatures = set()


def _error_signature(exctype, tb):
    """Identify a fault by its type and the frame that raised it.

    Two occurrences of the same bug at the same line share a signature. The
    message is deliberately left out of the key, so what the key distinguishes
    is a raise site and not a problem: distinct problems raised from one shared
    ``raise`` statement -- the malformed-option errors from ``Series.getOption``
    are such a site -- collapse into a single report. Including the message
    would separate them, at the cost of defeating deduplication entirely for any
    fault whose message embeds a value that varies between occurrences (a
    coordinate, a filename, a section number), which is exactly the storm case.

    Returns None when there is no usable traceback, which the caller reads as
    "cannot be recognised again, so always report it".
    """
    try:
        frame = traceback.extract_tb(tb)[-1]
        return (getattr(exctype, "__name__", str(exctype)), frame.filename, frame.lineno)
    except Exception:
        return None


def customExcepthook(exctype, value, tb):
    """Global exception hook: show an error window with a copyable report.

    A given fault opens one window per session. The hook used to open one per
    occurrence, which is fine for a fault the user can stop provoking and a trap
    for one they cannot: an exception raised from a ``paintEvent`` recurs on
    every repaint, and closing its error window exposes the widget underneath,
    which repaints, which raises, which opens the next window. Reported on 1.21.0
    as an unstoppable stream of error windows that left Task Manager as the only
    way out.

    Deduplicating rather than rate-limiting is deliberate. A delay between
    windows would still leave the user closing them forever; what they need is
    for the app to say this once and then let them save their work and quit.
    Every occurrence is still written to the log file below, so nothing about the
    repetition is lost -- ``Help > View log file`` shows it.

    A fault is only marked reported once a window has actually opened for it. A
    report can be suppressed here without being shown, because
    ``show_error_report`` refuses to open one from inside another's modal loop,
    and a fault whose window never appeared has not had its turn: marking it
    reported would spend the one window it is owed on nothing, and the user
    would never see it, in this session or any later moment of it. The startup
    timers ``MainWindow`` schedules make that ordinary rather than exotic -- they
    fire inside a report window's loop if one is up in the first few seconds.
    """
    sys.__excepthook__(exctype, value, tb)  # keep console output for terminal users

    report = build_error_report(exctype, value, tb)

    # Also record it in the log file, so it survives after the dialog is closed
    # and can be pulled up via Help > View log file (best-effort). Every
    # occurrence is logged, including the ones whose window is suppressed below.
    try:
        from PyReconstruct.modules.backend.func.logging_setup import log_file_path
        with open(log_file_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write("\n" + report + "\n")
    except Exception:
        pass

    signature = _error_signature(exctype, tb)
    if signature is not None and signature in _reported_signatures:
        return

    # Line breaks are kept, the way show_save_error keeps them: an exception
    # whose message is several lines (the malformed-option errors from
    # Series.getOption spell out the expected shape and the fix on their own
    # lines) otherwise arrives as one run-on paragraph, because the summary is
    # rich text and a bare newline is whitespace there.
    message = html.escape(str(value)).replace("\n", "<br>")
    lead = (
        f"<b>An error occurred:</b><br><br>{message}<br><br>"
        "If this error happens again it will be written to the log file "
        "(<b>Help &gt; View log file</b>) instead of opening another window."
    )
    # Only spend this fault's one window once one has actually opened.
    if show_error_report(_standard_summary(lead), report) and signature is not None:
        _reported_signatures.add(signature)

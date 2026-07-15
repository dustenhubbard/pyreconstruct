import os
import sys
import html

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
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._report)
        self._copy_btn.setText("Copied ✓")


def show_error_report(summary_html: str, report: str, parent=None, title="Error"):
    """Show ``report`` in a copyable dialog, never letting the display itself fail.

    Shared by the global exception hook, the handled save-error path, and the
    Help-menu diagnostics action. Falls back to a plain message box if the rich
    dialog cannot be constructed.
    """
    active_window = QApplication.activeWindow()
    if parent is None:
        parent = active_window

    try:
        dialog = ErrorReportDialog(summary_html, report, parent)
        dialog.setWindowTitle(title)
        dialog.exec()
    except Exception:
        # the error handler itself must never fail -- fall back to a plain box
        QMessageBox.critical(parent, title, f"{report}\n\n{gh_issues}", QMessageBox.Ok)

    if active_window:
        active_window.activateWindow()


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


def customExcepthook(exctype, value, tb):
    """Global exception hook: show an error window with a copyable report."""
    sys.__excepthook__(exctype, value, tb)  # keep console output for terminal users

    report = build_error_report(exctype, value, tb)

    # Also record it in the log file, so it survives after the dialog is closed
    # and can be pulled up via Help > View log file (best-effort).
    try:
        from PyReconstruct.modules.backend.func.logging_setup import log_file_path
        with open(log_file_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write("\n" + report + "\n")
    except Exception:
        pass

    lead = f"<b>An error occurred:</b><br><br>{html.escape(str(value))}"
    show_error_report(_standard_summary(lead), report)

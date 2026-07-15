import sys
import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
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
    lead = f"<b>An error occurred:</b><br><br>{html.escape(str(value))}"
    show_error_report(_standard_summary(lead), report)

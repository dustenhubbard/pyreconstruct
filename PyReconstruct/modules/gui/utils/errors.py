import sys
import html
import platform
import traceback as _traceback

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


def build_error_report(exctype, value, tb) -> str:
    """Assemble a paste-ready crash report: version / OS / Python context plus the
    full traceback. Never raises -- the global exception hook must not itself fail.
    """
    lines = ["PyReconstruct error report"]
    try:
        from PyReconstruct.modules.backend.updater.install_info import current_version_str
        lines.append(f"Version:  {current_version_str()}")
    except Exception:
        pass
    try:
        lines.append(f"Platform: {platform.platform()}")
        lines.append(f"Python:   {platform.python_version()}")
    except Exception:
        pass
    lines.append("")
    try:
        tb_text = "".join(_traceback.format_exception(exctype, value, tb)).rstrip()
    except Exception:
        tb_text = f"{getattr(exctype, '__name__', exctype)}: {value}"
    lines.append(tb_text or "(no traceback available)")
    return "\n".join(lines)


class ErrorReportDialog(QDialog):
    """Modal error window that shows a copyable report.

    The frozen app has no console, so lay users cannot read the traceback that
    ``sys.__excepthook__`` prints to stderr. This shows the full report inline and
    a one-click "Copy report to clipboard" button so it can be pasted into a bug
    report or email.
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


def customExcepthook(exctype, value, tb):
    """Global exception hook: show an error window with a copyable report."""
    sys.__excepthook__(exctype, value, tb)  # keep console output for terminal users

    report = build_error_report(exctype, value, tb)

    summary = (
        f"<b>An error occurred:</b><br><br>{html.escape(str(value))}<br><br>"
        "Click <b>Copy report to clipboard</b> below, then paste it into a bug "
        "report or email so we can help.<br><br>"
        f'Report bugs at <a href="{gh_issues}">{gh_issues}</a>'
    )

    active_window = QApplication.activeWindow()
    parent = active_window if active_window else None

    try:
        ErrorReportDialog(summary, report, parent).exec()
    except Exception:
        # the error handler itself must never fail -- fall back to a plain box
        QMessageBox.critical(
            parent, "Error", f"{str(value)}\n\n{gh_issues}", QMessageBox.Ok
        )

    if active_window:
        active_window.activateWindow()

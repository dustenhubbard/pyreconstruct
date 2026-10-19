from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .helper import BorderedWidget

from PyReconstruct.modules.datatypes import local_stores

EXPLAIN = (
    "Keeps a copy of each series on this computer so it opens in seconds. "
    "The .jser file stays the one you share."
)


def sizeText(n : int) -> str:
    """A folder size as a person reads it."""
    if n <= 0:
        return "none"
    if n < 1024 ** 2:
        return "under 1 MB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.0f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def removedText(report) -> str:
    """What the Remove button did, in a line or two."""
    n = len(report.removed)
    text = f"Removed {n} local {'copy' if n == 1 else 'copies'}."
    kept = [why for _, why in report.kept if why]
    if kept:
        reasons = "; ".join(dict.fromkeys(kept))
        text += f" Kept {len(kept)}: {reasons}."
    return text


class LocalStoreOptionWidget(BorderedWidget):
    """The "Fast local copy for large series" row of Series > Options.

    Dev builds only (all_options.py). One check box for the per-user setting,
    and a button that removes the local copies cleanup may remove, with the
    folder's size beside it. The setting waits for OK like every other
    option; the button acts at once, since it only removes copies that hold
    nothing their .jser lacks.
    """

    def __init__(self, parent, series, use_defaults=False):
        super().__init__(parent)
        self.series = series
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(8, 6, 8, 8)

        self.check = QCheckBox("Fast local copy for large series", self)
        self.check.setChecked(bool(series.getOption(local_stores.SETTING, use_defaults)))
        layout.addWidget(self.check)
        explain = QLabel(EXPLAIN, self)
        explain.setWordWrap(True)
        layout.addWidget(explain)
        if local_stores.switchIsSet():
            state = "on" if local_stores.enabled() else "off"
            switch = QLabel(
                f"{local_stores.ENV_SWITCH} is set, so it decides for now: the copy is {state}.",
                self,
            )
            switch.setWordWrap(True)
            layout.addWidget(switch)

        row = QHBoxLayout()
        self.remove_button = QPushButton("Remove local copies", self)
        self.remove_button.clicked.connect(self.removeCopies)
        row.addWidget(self.remove_button)
        self.size_label = QLabel(self)
        row.addWidget(self.size_label)
        row.addStretch()
        layout.addLayout(row)
        self.result_label = QLabel(self)
        self.result_label.setWordWrap(True)
        self.result_label.setHidden(True)
        layout.addWidget(self.result_label)
        # the rows at the top, however tall the tab is
        layout.addStretch()

        self.setLayout(layout)
        self.addTitle("Fast Local Copy")
        self.showSize()

    def showSize(self):
        size = local_stores.folderSize()
        self.size_label.setText(f"Local copies on this computer: {sizeText(size)}")
        self.remove_button.setEnabled(size > 0)

    def removeCopies(self):
        """Remove every local copy that holds nothing its .jser lacks."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            report = local_stores.removeClean()
        finally:
            QApplication.restoreOverrideCursor()
        self.result_label.setText(removedText(report))
        self.result_label.setHidden(False)
        self.showSize()

    # --- options-dialog protocol (accept -> set) -----------------------------

    def accept(self, close=True):
        return True

    def set(self):
        local_stores.setSetting(self.series, self.check.isChecked())

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)

from PyReconstruct.modules.gui.utils import notify


def parse_section_spec(text : str, valid_sections) -> tuple:
    """Parse a section spec string into a set of section numbers.

    Accepts comma/space-separated tokens, each either a single number ("12")
    or an inclusive range ("10-15"). Returns the parsed numbers that exist in
    valid_sections, plus a list of tokens that were malformed or out of range.

        Params:
            text (str): the spec, e.g. "10-15, 20, 22"
            valid_sections (iterable): the section numbers that exist
        Returns:
            (tuple): (set of valid section numbers, list of bad tokens)
    """
    valid = set(valid_sections)
    chosen = set()
    bad = []

    for token in text.replace(",", " ").split():
        if "-" in token.strip("-"):  # a range like 10-15
            parts = token.split("-")
            if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
                bad.append(token)
                continue
            lo, hi = int(parts[0]), int(parts[1])
            if lo > hi:
                lo, hi = hi, lo
            matched = [n for n in range(lo, hi + 1) if n in valid]
            if not matched:
                bad.append(token)
            chosen.update(matched)
        else:  # a single section number
            if not token.isdigit():
                bad.append(token)
                continue
            n = int(token)
            if n in valid:
                chosen.add(n)
            else:
                bad.append(token)

    return chosen, bad


class CopyToSectionsDialog(QDialog):
    """Pick the target sections to copy the selected trace(s) onto."""

    def __init__(self, parent, series):
        super().__init__(parent)
        self.series = series
        self.valid_sections = set(series.sections.keys())
        self.sections = None

        current = series.current_section
        smin, smax = min(self.valid_sections), max(self.valid_sections)

        self.setWindowTitle("Copy to sections")

        vlayout = QVBoxLayout()

        info = QLabel(self, text=(
            "Copy the selected trace(s) onto other sections at the same "
            "location.\n"
            f"The current section ({current}) is left unchanged.\n"
            f"Enter section numbers or ranges from {smin} to {smax}, "
            "e.g. \"10-20\" or \"5, 8, 11\"."
        ))
        vlayout.addWidget(info)

        self.spec_input = QLineEdit(self)
        self.spec_input.setPlaceholderText("e.g. 10-20 or 5, 8, 11")
        vlayout.addWidget(self.spec_input)

        buttonbox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)
        vlayout.addSpacing(10)
        vlayout.addWidget(buttonbox)

        self.setLayout(vlayout)

    def accept(self):
        chosen, bad = parse_section_spec(
            self.spec_input.text(), self.valid_sections
        )
        if bad:
            notify("Invalid or out-of-range section(s): " + ", ".join(bad))
            return
        if not chosen:
            notify("Please enter at least one valid section.")
            return
        self.sections = chosen
        super().accept()

    def get(self):
        """Run the dialog.

            Returns:
                (tuple): (set of section numbers, confirmed bool)
        """
        if self.exec():
            return self.sections, True
        return None, False

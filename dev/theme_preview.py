"""Standalone visual preview for the UI theme engine (gui.utils.theme).

A tiny window of representative Qt widgets driven by the REAL theme module, for
signing off the light/dark themes, the azure accent, and OS-scheme following on
a machine with a real display (macOS or Windows). It loads theme.py directly by
path, so the only dependencies are PySide6 and qdarkstyle — none of the heavy
PyReconstruct runtime deps (vtk/vedo/zarr/...).

    pip install PySide6==6.5.2 qdarkstyle==3.2.3
    python dev/theme_preview.py

The System/Light/Dark buttons APPLY a theme in-memory only; they do NOT write to
QSettings, so running this never disturbs the real app's saved theme preference.
The app's currently-saved preference is shown read-only for reference.

What to check:
  * macOS — the ideal platform: in System mode the chrome follows the OS, and
    flipping System Settings -> Appearance (Light/Dark) updates it live. The
    "OS colorScheme()" line should read Light/Dark accordingly.
  * Windows — chrome should follow Settings -> Personalization -> Colors. Live
    switching may lag on Qt 6.5; toggling here confirms the look regardless.
  * Judge: light-mode legibility, the calm-azure accent on the selected list /
    table rows and the highlighted menu item, and that the modal dialog inherits
    the theme. Tune theme.ACCENT (and the other tokens) if needed.
"""
import importlib.util
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox, QCheckBox, QRadioButton,
    QListWidget, QTableWidget, QTableWidgetItem, QProgressBar, QTabWidget,
    QGroupBox, QDialog, QDialogButtonBox, QPlainTextEdit,
)

# --- load the real theme engine standalone (no package __init__) -------------
_THEME_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "PyReconstruct", "modules", "gui", "utils", "theme.py",
))
_spec = importlib.util.spec_from_file_location("pyrecon_theme_preview", _THEME_PATH)
theme = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(theme)


def _colorscheme_name(app):
    try:
        s = app.styleHints().colorScheme()
        return {Qt.ColorScheme.Light: "Light",
                Qt.ColorScheme.Dark: "Dark"}.get(s, "Unknown")
    except Exception:
        return "Unknown"


class Preview(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyReconstruct — theme preview")
        self.resize(760, 620)
        self.mode = theme.normalize_mode(theme.read_mode())  # start from saved pref

        # menu: Theme chooser + a dummy menu so menu styling is visible
        theme_menu = self.menuBar().addMenu("Theme")
        self._mode_acts = {}
        for m in theme.MODES:
            act = theme_menu.addAction(m.capitalize())
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, mm=m: self.set_mode(mm))
            self._mode_acts[m] = act
        view = self.menuBar().addMenu("View")
        view.addAction("Some item")
        view.addAction("Another item")
        view.addSeparator()
        view.addAction("Disabled item").setEnabled(False)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        root.addWidget(self.status)

        # mode toggle buttons
        row = QHBoxLayout()
        row.addWidget(QLabel("Mode:"))
        self._mode_btns = {}
        for m in theme.MODES:
            b = QPushButton(m.capitalize())
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, mm=m: self.set_mode(mm))
            row.addWidget(b)
            self._mode_btns[m] = b
        row.addStretch(1)
        dlg_btn = QPushButton("Open a dialog…")
        dlg_btn.clicked.connect(self.open_dialog)
        row.addWidget(dlg_btn)
        root.addLayout(row)

        root.addWidget(self._controls_group())

        # selection accent surfaces: a list and a table, both pre-selected
        sel_row = QHBoxLayout()
        lst = QListWidget()
        for i in range(7):
            lst.addItem(f"List item {i + 1}")
        lst.setCurrentRow(2)
        sel_row.addWidget(lst)

        tbl = QTableWidget(5, 3)
        tbl.setHorizontalHeaderLabels(["Object", "Count", "Volume"])
        for r in range(5):
            for c in range(3):
                tbl.setItem(r, c, QTableWidgetItem(f"r{r}c{c}"))
        tbl.selectRow(1)
        sel_row.addWidget(tbl)
        root.addLayout(sel_row)

        pb = QProgressBar()
        pb.setValue(62)
        root.addWidget(pb)

        self.refresh()

    def _controls_group(self):
        g = QGroupBox("Controls")
        grid = QGridLayout(g)
        b1 = QPushButton("Button")
        b2 = QPushButton("Default")
        b2.setDefault(True)
        b3 = QPushButton("Disabled")
        b3.setEnabled(False)
        b4 = QPushButton("Checked")
        b4.setCheckable(True)
        b4.setChecked(True)
        grid.addWidget(b1, 0, 0)
        grid.addWidget(b2, 0, 1)
        grid.addWidget(b3, 0, 2)
        grid.addWidget(b4, 0, 3)
        grid.addWidget(QLineEdit("editable text"), 1, 0, 1, 2)
        combo = QComboBox()
        combo.addItems(["Alpha", "Beta", "Gamma"])
        grid.addWidget(combo, 1, 2)
        grid.addWidget(QSpinBox(), 1, 3)
        grid.addWidget(QCheckBox("Checkbox"), 2, 0)
        rb = QRadioButton("Radio")
        rb.setChecked(True)
        grid.addWidget(rb, 2, 1)

        tabs = QTabWidget()
        t1 = QPlainTextEdit("Tab one — multiline text area.")
        tabs.addTab(t1, "Tab one")
        tabs.addTab(QWidget(), "Tab two")
        grid.addWidget(tabs, 3, 0, 1, 4)
        return g

    def set_mode(self, mode):
        # apply only — never persist, so the real app's saved theme is untouched
        self.mode = theme.normalize_mode(mode)
        theme.apply_theme(QApplication.instance(), self.mode)
        self.refresh()

    def on_os_scheme_changed(self, *_):
        if self.mode == "system":
            theme.apply_theme(QApplication.instance(), "system")
        self.refresh()

    def refresh(self):
        app = QApplication.instance()
        scheme = theme.current_scheme(app, self.mode)
        os_name = _colorscheme_name(app)
        saved = theme.read_mode()
        for m, act in self._mode_acts.items():
            act.setChecked(m == self.mode)
        for m, btn in self._mode_btns.items():
            btn.setChecked(m == self.mode)
        self.status.setText(
            f"<b>Selected mode:</b> {self.mode} &nbsp;|&nbsp; "
            f"<b>Resolved scheme:</b> {scheme} &nbsp;|&nbsp; "
            f"<b>OS colorScheme():</b> {os_name} &nbsp;|&nbsp; "
            f"<b>App's saved pref:</b> {saved} &nbsp;|&nbsp; "
            f"<b>accent:</b> {theme.ACCENT}"
        )
        self.statusBar().showMessage(
            f"theme.py @ {_THEME_PATH}  —  apply-only (saved preference not modified)"
        )

    def open_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("A modal dialog")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Dialogs inherit the app stylesheet too.\n"
                             "Check this reads cleanly in light and dark."))
        lay.addWidget(QLineEdit("a field"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.exec()


def main():
    app = QApplication(sys.argv)
    w = Preview()
    # mirror the app: in System mode, follow live OS light/dark switches
    try:
        app.styleHints().colorSchemeChanged.connect(w.on_os_scheme_changed)
    except Exception:
        pass
    theme.apply_theme(app, w.mode)
    w.refresh()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

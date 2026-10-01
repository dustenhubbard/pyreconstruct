"""Renaming the current alignment in `Alignments` > `Edit alignments...` keeps it on.

With no row selected, OK keeps the current alignment. When that alignment was
renamed in the dialog, the old name no longer exists after OK, and the view
fell back to `no-alignment`. The real dialog runs here; only the name prompt
is stubbed.
"""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QPushButton

pytestmark = pytest.mark.gui


def _run(main_window, monkeypatch, steps):
    """Open the dialog, run steps(dialog) inside it, then press OK."""
    from PyReconstruct.modules.gui.main import main_window as mw_mod
    from PyReconstruct.modules.gui.dialog.alignment import AlignmentDialog

    class Driven(AlignmentDialog):
        def exec(self):
            def act():
                steps(self)
                self.table.clearSelection()
                self.accept()
            QTimer.singleShot(0, act)
            return super().exec()

    monkeypatch.setattr(mw_mod, "AlignmentDialog", Driven)
    main_window.modifyAlignments()


def _select(dialog, name):
    table = dialog.table
    for r in range(table.rowCount()):
        if table.item(r, 0).text() == name:
            table.selectRow(r)
            return
    raise AssertionError(f"no row {name!r}")


def _button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


def _rename(monkeypatch, dialog, old, new):
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: (new, True))
    )
    _select(dialog, old)
    _button(dialog, "Rename...").click()


def test_renaming_the_current_alignment_keeps_it_on(main_window, monkeypatch):
    current = main_window.series.alignment
    assert current != "no-alignment"

    _run(main_window, monkeypatch,
         lambda d: _rename(monkeypatch, d, current, "renamed"))

    assert main_window.series.alignment == "renamed"
    assert "renamed" in main_window.field.section.tforms
    assert main_window.renamed_alignment_act.isChecked()


def test_two_renames_follow_the_current_alignment(main_window, monkeypatch):
    current = main_window.series.alignment

    def steps(dialog):
        _rename(monkeypatch, dialog, current, "first")
        _rename(monkeypatch, dialog, "first", "second")

    _run(main_window, monkeypatch, steps)

    assert main_window.series.alignment == "second"


def test_removing_the_current_alignment_still_turns_it_off(main_window,
                                                          monkeypatch):
    current = main_window.series.alignment

    def steps(dialog):
        _select(dialog, current)
        _button(dialog, "Remove").click()

    _run(main_window, monkeypatch, steps)

    assert main_window.series.alignment == "no-alignment"

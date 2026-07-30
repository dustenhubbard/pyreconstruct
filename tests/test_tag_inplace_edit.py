"""Tests for editing an existing tag in place.

Tags are edited on two surfaces and each had its own reason a partial edit did
not survive:

* ``Trace > Edit trace attributes...`` gives every tag its own line edit
  (``MultiInput``), but "-" popped the *last* row wherever the caret was, so
  correcting the first of several tags meant deleting the rows after it and
  typing them again. The rows also came straight out of a set, so a tag moved
  between openings.
* The trace palette's Tags column is one comma-separated cell. It was parsed
  with ``text.split(", ")``, which turns the "axon, " left behind by deleting
  "spine" into two tags, the second of them empty, and turns an untagged
  trace's empty cell into a single empty tag.

None of this covers the click itself. What it covers is what the widgets do
when driven through their real slots.
"""

import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.dialog import trace as trace_dialog_module
from PyReconstruct.modules.gui.dialog.helper import MultiInput
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickTabDialog
from PyReconstruct.modules.gui.dialog.trace import TraceDialog
from PyReconstruct.modules.gui.dialog.trace_palette import (
    TracePaletteDialog,
    parseTags,
)


def _trace(tags):
    """A minimal closed trace carrying the given tags."""
    t = Trace("axon", (255, 0, 0))
    t.points = [(0, 0), (1, 0), (1, 1)]
    t.tags = set(tags)
    return t


def _shown(widget):
    """Show and activate a widget so that setFocus() actually takes effect.

    Offscreen Qt hands out no focus at all until a window is active, so a test
    that drives focus has to ask for it explicitly.
    """
    from PySide6.QtWidgets import QApplication

    widget.show()
    widget.activateWindow()
    QApplication.instance().processEvents()
    return widget


# --- parseTags (pure) -------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("", []),                                   # an untagged trace's cell
    ("   ", []),
    ("axon", ["axon"]),
    ("axon, spine", ["axon", "spine"]),
    ("axon, ", ["axon"]),                       # "spine" deleted off the end
    (", spine", ["spine"]),                     # "axon" deleted off the front
    ("axon,,spine", ["axon", "spine"]),         # a tag deleted from the middle
    ("axon,spine", ["axon", "spine"]),          # separator typed without a space
    ("  axon ,  spine  ", ["axon", "spine"]),
])
def test_parse_tags(text, expected):
    assert parseTags(text) == expected


# --- the palette's Tags column ---------------------------------------------


@pytest.fixture
def palette_dialog(qapp, real_series, monkeypatch):
    """A real TracePaletteDialog whose exec() does not block.

    ``TracePaletteDialog.exec`` calls up to ``QuickDialog.exec``, which spins a
    modal loop that offscreen Qt has nobody to dismiss. Replacing the inherited
    exec with the responses the widgets already produced leaves the part under
    test, the palette write-back, running for real.
    """
    from PySide6.QtWidgets import QWidget

    monkeypatch.setattr(
        QuickTabDialog, "exec", lambda self: (self.responses, True)
    )
    parent = QWidget()
    dialog = TracePaletteDialog(parent, real_series)
    yield dialog
    dialog.deleteLater()
    parent.deleteLater()


def _tags_field(dialog, palette_name, row):
    """The Tags line edit for one palette row (7 fields per trace)."""
    return dialog.inputs[palette_name][row * 7 + 3].widget


def _all_palette_tags(series):
    return [
        t.tags
        for traces in series.palette_traces.values()
        for t in traces
    ]


def test_palette_untagged_trace_stays_untagged(palette_dialog, real_series):
    # every palette trace in the fixture series starts untagged, so accepting
    # the dialog untouched used to give all 20 of them a single empty tag
    palette_dialog.accept()
    palette_dialog.exec()

    assert all(tags == set() for tags in _all_palette_tags(real_series))


def test_palette_partial_delete_leaves_the_remaining_tag(
    palette_dialog, real_series
):
    name = next(iter(palette_dialog.inputs))
    _tags_field(palette_dialog, name, 0).setText("axon, spine")
    _tags_field(palette_dialog, name, 1).setText("axon, ")

    palette_dialog.accept()
    palette_dialog.exec()

    traces = real_series.palette_traces[name]
    assert traces[0].tags == {"axon", "spine"}
    assert traces[1].tags == {"axon"}
    assert not any("" in tags for tags in _all_palette_tags(real_series))


def test_palette_tags_cell_is_ordered():
    """The cell text is sorted, so a tag does not move between openings."""
    structure = TracePaletteDialog.getStructure(
        None, [_trace({"zeta", "alpha", "mu"})]
    )
    assert structure[1][3] == ("text", "alpha, mu, zeta")


# --- MultiInput, the trace attributes dialog's tag rows --------------------


def test_remove_takes_the_row_being_edited(qapp):
    from PySide6.QtWidgets import QWidget

    from PySide6.QtWidgets import QVBoxLayout

    host = QWidget()
    field = MultiInput(host, ["axon", "spine", "dendrite"])
    layout = QVBoxLayout()
    layout.addWidget(field)
    host.setLayout(layout)
    _shown(host)

    field.inputs[0].setFocus()
    qapp.processEvents()
    assert field.currentIndex() == 0

    field.remove()
    assert field.getEntries() == ["spine", "dendrite"]

    host.deleteLater()


def test_remove_falls_back_to_the_last_row(qapp):
    """With the caret nowhere in the field, "-" keeps its old meaning."""
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    field = MultiInput(host, ["axon", "spine", "dendrite"])

    field.remove()
    assert field.getEntries() == ["axon", "spine"]

    host.deleteLater()


def test_removing_the_only_row_clears_it_instead(qapp):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    field = MultiInput(host, ["axon"])

    field.remove()
    assert field.getEntries() == []
    assert len(field.inputs) == 1  # still a line edit to type into

    field.remove()
    assert len(field.inputs) == 1

    host.deleteLater()


def test_add_remove_buttons_do_not_steal_focus(qapp):
    """The premise of the fix: "-" can only know which row the caret is in if
    clicking it leaves the caret alone."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton, QWidget

    host = QWidget()
    field = MultiInput(host, ["axon"])
    buttons = field.findChildren(QPushButton)

    assert [b.text() for b in buttons] == ["-", "+"]
    assert all(b.focusPolicy() == Qt.NoFocus for b in buttons)

    host.deleteLater()


# --- the trace attributes dialog ------------------------------------------


def test_trace_dialog_lists_tags_in_a_stable_order(qapp, monkeypatch):
    """The dialog hands MultiInput an ordered sequence, not the raw set."""
    captured = []
    real_multi_input = trace_dialog_module.MultiInput

    def recording(parent, entries=None, *args, **kwargs):
        captured.append(entries)
        return real_multi_input(parent, entries, *args, **kwargs)

    monkeypatch.setattr(trace_dialog_module, "MultiInput", recording)

    dialog = TraceDialog(None, traces=[_trace({"zeta", "alpha", "mu"})])

    assert captured == [["alpha", "mu", "zeta"]]
    assert [w.text() for w in dialog.tags_input.inputs] == [
        "alpha", "mu", "zeta"
    ]

    dialog.deleteLater()


def test_trace_dialog_drops_a_tag_cleared_in_place(qapp):
    """Clearing a tag's text is how a single tag is deleted; the dialog must
    not return it as an empty tag."""
    dialog = TraceDialog(None, traces=[_trace({"axon", "spine"})])

    dialog.tags_input.inputs[0].setText("")
    assert dialog.tags_input.getEntries() == ["spine"]

    dialog.deleteLater()

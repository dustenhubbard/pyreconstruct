"""The object attributes dialog must show the object's color, and only show it.

The bug this pins, reported twice against the "Set Attributes" dialog opened
from an object selection (once by a Windows user whose report circulated for
a week as a suspected platform color defect, once by the maintainer's own
click test): the color swatch is gray and the picker opens on white even
though the object has a perfectly good color. ``editAttributes`` constructed
``TraceDialog`` with ``name`` and ``tags`` but never passed ``color``, so the
swatch was unseeded for every object, always.

Seeding it is not enough on its own, and the second half of this file exists
because of why: the dialog writes the swatch's color back to every trace of
every selected object on OK. A seed that merely displays the current color
would, on an untouched OK, repaint an object whose OTHER sections hold
different colors to the one color the open section happened to show. So the
seed is display-only: ``TraceDialog.exec`` returns ``color=None`` (which every
consumer reads as "leave the existing colors alone") unless the user actually
confirmed a color in the picker, which ``ColorButton`` now records in its
``picked`` flag. This is the same distinction the tags field draws with
``tags_mixed``: a value the dialog put there is not a value the user chose.

The seed itself comes from ``object_color_seed``, and it is SERIES-WIDE: one
agreed color shows solid, any disagreement shows the predominant color as a
split, wherever in the series the minority traces live. A first cut answered
from the open section only, and the maintainer's click test caught the gap
the same day: recolor one trace, move to an adjacent section, open the dialog
on the same object, no split. ``SeriesData``'s per-trace records carry color
now (exactly as they carry tags) so the series-wide answer costs no section
load; the cross-section case is pinned below against the data a fresh
refresh reads off disk.
"""

import os
import shutil

import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QWidget

from PyReconstruct.modules.gui.dialog import color_button as color_button_module
from PyReconstruct.modules.gui.dialog.color_button import ColorButton
from PyReconstruct.modules.gui.dialog.trace import TraceDialog
from PyReconstruct.modules.gui.main.field_widget_3_object import object_color_seed

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)

YELLOW = (255, 255, 0)
GREEN = (0, 255, 0)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _recolor(series, obj_name, color, sections=None):
    """Recolor an object through the app's own write path, then re-read.

    ``editObjectAttributes`` writes the sections to disk; the refresh makes
    ``series.data`` re-derive its per-trace records from what was actually
    stored, so these tests exercise the same data the dialog will read.
    """
    series.editObjectAttributes(
        [obj_name], color=list(color), sections=sections, log_event=False
    )
    series.data.refresh()


def _colors_on_disk(series, obj_name):
    """Every stored trace's color for one object, read back per section.

    An independent read path (straight off the sections, not through
    SeriesData), so the expected counts do not come from the code under
    test.
    """
    out = []
    for snum, section in series.enumerateSections(show_progress=False):
        if obj_name in section.contours:
            for trace in section.contours[obj_name].getTraces():
                out.append(tuple(trace.color) if trace.color else None)
    assert out, f"object {obj_name} had no traces to check"
    return out


def _spanning_object(series):
    """An object with traces on at least two sections, or skip."""
    for name, obj_data in series.data["objects"].items():
        if len(obj_data.traces) >= 2:
            return name
    pytest.skip("fixture has no object spanning two sections")


class AcceptingColorDialog(QColorDialog):
    """A real dialog whose exec accepts a fixed color instead of blocking."""

    chosen = GREEN

    def exec(self):
        self.setCurrentColor(QColor(*type(self).chosen))
        self.done(QDialog.DialogCode.Accepted)
        return QDialog.DialogCode.Accepted


class RejectingColorDialog(QColorDialog):
    """A real dialog whose exec cancels instead of blocking."""

    def exec(self):
        self.done(QDialog.DialogCode.Rejected)
        return QDialog.DialogCode.Rejected


@pytest.fixture
def parent(qapp):
    """A dialog parent carrying the one attribute the obj-list rows read.

    ``TraceDialog(is_obj_list=True)`` fills its section-range row from
    ``parent.series.sections``; a two-section stub keeps these tests off the
    full field-widget stack.
    """
    from types import SimpleNamespace
    w = QWidget()
    w.series = SimpleNamespace(sections={0: None, 1: None})
    yield w
    w.deleteLater()


# --------------------------------------------------------------------------- #
# the seed: agreed color, or predominant-plus-mixed, or blank; series-wide     #
# --------------------------------------------------------------------------- #
def test_seed_is_the_objects_color(qapp, tmp_path):
    series = _load_series(tmp_path)
    name = next(iter(series.data["objects"]))
    _recolor(series, name, YELLOW)
    assert object_color_seed(series.data, [name]) == (YELLOW, False)


def test_a_recolored_trace_on_another_section_flags_mixed(qapp, tmp_path):
    """The maintainer's click-test repro, pinned.

    Recolor an object on ONE of its sections, then ask for the seed the way
    the dialog does when opened from any other section. The first cut of
    this feature answered from the open section only and showed a solid
    swatch here; the answer must be mixed no matter which section the
    dialog is opened from, because the dialog's OK fans out to all of them.
    """
    series = _load_series(tmp_path)
    name = _spanning_object(series)
    _recolor(series, name, YELLOW)
    one_section = min(series.data["objects"][name].traces.keys())
    _recolor(series, name, GREEN, sections=(one_section,))

    on_disk = _colors_on_disk(series, name)
    assert set(on_disk) == {YELLOW, GREEN}, "the repro needs both colors stored"
    expected = max(
        {c: on_disk.count(c) for c in set(on_disk)},
        key=lambda c: (on_disk.count(c), c),
    )

    color, mixed = object_color_seed(series.data, [name])
    assert mixed is True
    assert color == expected


class _StubData:
    """Only what object_color_seed touches: getColorCounts(name)."""

    def __init__(self, counts_by_name):
        self._counts = counts_by_name

    def getColorCounts(self, name):
        return self._counts.get(name, {})


def test_disagreeing_traces_seed_the_predominant_color_as_mixed(qapp):
    """More yellow traces than green: yellow shows, flagged mixed.

    The mixed flag is what the swatch renders as a diagonal split, so the
    user editing the object is keyed into the discrepancy instead of seeing
    a solid swatch that silently misrepresents the minority traces.
    """
    data = _StubData({"a": {YELLOW: 2}, "b": {GREEN: 1}})
    assert object_color_seed(data, ["a", "b"]) == (YELLOW, True)


def test_a_tie_is_still_flagged_mixed_and_stays_stable(qapp):
    """Equal counts: still a discrepancy, and the shown color is stable.

    The tie-break is the color triple itself, so the same selection shows
    the same swatch on every open rather than flickering with dict order.
    """
    data = _StubData({"a": {YELLOW: 1}, "b": {GREEN: 1}})
    color, mixed = object_color_seed(data, ["a", "b"])
    assert mixed is True
    assert color == max([YELLOW, GREEN])


def test_seed_is_blank_for_an_unknown_object(qapp, tmp_path):
    series = _load_series(tmp_path)
    assert series.data.getColorCounts("no-such-object") == {}
    assert object_color_seed(series.data, ["no-such-object"]) == (None, False)


# --------------------------------------------------------------------------- #
# the guard: a seeded, untouched swatch means "leave the colors alone"         #
# --------------------------------------------------------------------------- #
def _exec_accepted(dialog, monkeypatch):
    """Accept the attributes dialog itself without a modal loop."""
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    return dialog.exec()


def test_untouched_seeded_swatch_returns_no_color(qapp, parent, monkeypatch):
    dlg = TraceDialog(parent, name="obj", color=YELLOW, is_obj_list=True)
    (trace, _sections), confirmed = _exec_accepted(dlg, monkeypatch)
    assert confirmed
    assert trace.color is None, (
        "a seeded swatch the user never touched must not write a color back; "
        "on a mixed-color object it would repaint every trace to the one "
        "color the open section happened to show"
    )


def test_picked_color_is_returned(qapp, parent, monkeypatch):
    monkeypatch.setattr(color_button_module, "QColorDialog", AcceptingColorDialog)
    dlg = TraceDialog(parent, name="obj", color=YELLOW, is_obj_list=True)
    dlg.color_input.selectColor()  # the user picks green and confirms
    (trace, _sections), confirmed = _exec_accepted(dlg, monkeypatch)
    assert confirmed
    assert trace.color == GREEN


def test_swatch_displays_the_seed(qapp, parent):
    dlg = TraceDialog(parent, name="obj", color=YELLOW, is_obj_list=True)
    assert dlg.color_input.getColor() == YELLOW
    assert "255,255,0" in dlg.color_input.styleSheet()


# --------------------------------------------------------------------------- #
# the split: a mixed seed shows a diagonal, a pick makes it solid again        #
# --------------------------------------------------------------------------- #
def test_mixed_seed_renders_a_diagonal_split(qapp, parent):
    """Predominant color upper-left, blank lower-right, verified by pixels."""
    button = ColorButton(YELLOW, parent, mixed=True)
    assert button.mixed is True
    assert "qlineargradient" in button.styleSheet()
    button.resize(48, 24)
    img = button.grab().toImage()
    upper_left = img.pixelColor(6, 4)
    lower_right = img.pixelColor(img.width() - 7, img.height() - 5)
    assert (upper_left.red(), upper_left.green(), upper_left.blue()) == YELLOW
    assert (lower_right.red(), lower_right.green(), lower_right.blue()) != YELLOW


def test_untouched_mixed_swatch_still_returns_no_color(qapp, parent, monkeypatch):
    """The split is display only; the predominant color must not write back."""
    dlg = TraceDialog(
        parent, name="obj", color=YELLOW, color_mixed=True, is_obj_list=True
    )
    assert dlg.color_input.mixed is True
    (trace, _sections), confirmed = _exec_accepted(dlg, monkeypatch)
    assert confirmed
    assert trace.color is None


def test_confirmed_pick_replaces_the_split_with_a_solid(qapp, parent, monkeypatch):
    """The user's chosen color has no minority to disclose."""
    monkeypatch.setattr(color_button_module, "QColorDialog", AcceptingColorDialog)
    button = ColorButton(YELLOW, parent, mixed=True)
    button.selectColor()
    assert button.picked is True
    assert button.mixed is False
    assert "qlineargradient" not in button.styleSheet()
    assert button.getColor() == GREEN


def test_trace_selection_path_keeps_its_semantics(qapp, parent, monkeypatch):
    """The trace dialog (is_obj_list=False) still returns the seeded color.

    Its callers write the returned attributes back to exactly the traces the
    seed came from, so an untouched OK writing the same color back is the
    long-standing behavior and stays; the display-only rule is scoped to the
    object-list dialog, whose write fans out to sections the seed never saw.
    """
    dlg = TraceDialog(parent, name="t", color=YELLOW)
    trace, confirmed = _exec_accepted(dlg, monkeypatch)
    assert confirmed
    assert tuple(trace.color) == YELLOW


# --------------------------------------------------------------------------- #
# the flag: picked records a confirmed pick and nothing else                   #
# --------------------------------------------------------------------------- #
def test_picked_starts_false_and_seeding_keeps_it_false(qapp, parent):
    button = ColorButton(YELLOW, parent)
    assert button.picked is False
    button.setColor(GREEN)
    assert button.picked is False


def test_confirmed_pick_sets_picked(qapp, parent, monkeypatch):
    monkeypatch.setattr(color_button_module, "QColorDialog", AcceptingColorDialog)
    button = ColorButton(YELLOW, parent)
    button.selectColor()
    assert button.picked is True
    assert button.getColor() == GREEN


def test_cancelled_pick_leaves_picked_false(qapp, parent, monkeypatch):
    monkeypatch.setattr(color_button_module, "QColorDialog", RejectingColorDialog)
    button = ColorButton(YELLOW, parent)
    button.selectColor()
    assert button.picked is False
    assert button.getColor() == YELLOW

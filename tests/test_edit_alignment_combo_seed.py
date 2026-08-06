"""Regression tests for the object alignment dialog clearing what it never showed.

Bug: `FieldWidgetObject.editAlignment` built its dialog as

    [["Alignment:", ("combo", list(section.tforms.keys()))]]

with no third tuple element. `QuickDialog`'s combo branch reads that third
element as the initially-selected item, so absent it `selected` is `None`, the
combo prepends an empty `""` item, and `""` is what the dialog opens showing.
The field is not `required`, so `InputField.getResponse` returns `("", True)`
for it -- a *valid* response, not a refusal. `editAlignment` then does
`if not alignment: alignment = None` and writes that `None` to every selected
object, and `Series.setAttr` deletes the key on `None`. Opening the dialog and
pressing OK without touching it therefore removed the per-object alignment from
every selected object.

Not a rare opt-in override: `SeriesData.updateSection` runs
`self.series.setAttr(obj_name, "alignment", self.series.alignment)` for every
newly created object in its logging branch, so anything traced in this build
carries one. What falls back to the series alignment once it is gone includes
`SeriesData.addTraceData`'s choice of tform, `Section.editTraceRadius`, the
volume generators, the object list's Alignment column, and `editRadius`'s
"field alignment does not match the object alignment" prompt.

Fix: seed the combo with the selection's consensus alignment, computed the way
`edit3D` in the same file already computes its own -- first object's value,
dropping to `None` the moment two disagree. Because the field is not required
the blank item is prepended either way, so the seed only changes which entry
starts selected. Clearing an override stays available as a deliberate pick of
that blank entry; an untouched OK becomes a no-op.

Two things this deliberately does not change:

* A selection whose objects disagree still opens blank, and confirming it
  untouched still clears all of them. There is no single value to show, so the
  dialog cannot pre-fill one, and that is the same behavior as before.
* A stale alignment -- a name the current section no longer defines -- is not
  seeded. `InputField.getResponse` refuses combo text that `findText` cannot
  resolve, so seeding one would make OK unreachable. Such an object opens blank,
  exactly as it did before.
"""
import os
import shutil

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

_UNTOUCHED = object()


# ---------------------------------------------------------------------------
# fixture series
# ---------------------------------------------------------------------------
def _load_series(tmp_path):
    """shapes1.jser: 5 sections, 4 objects, two alignments (`default` and
    `no-alignment`). Two are the minimum needed to tell "they agree" from "they
    disagree"."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _two_objects(series):
    names = sorted(series.data["objects"].keys())
    if len(names) < 2:
        pytest.skip("fixture has fewer than two objects")
    return names[0], names[1]


# ---------------------------------------------------------------------------
# the surface `editAlignment` and its decorator touch
# ---------------------------------------------------------------------------
class _FakeStates:
    def __init__(self):
        self.states = 0

    def addState(self, *args, **kwargs):
        self.states += 1


class _FakeTableManager:
    def hasFocus(self):
        # Not an ObjectTableWidget, so `object_function` falls back to the
        # traces selected in the field for the selection.
        return None

    def updateObjects(self, names):
        pass

    def refresh(self):
        pass


class _FakeMainWindow:
    def __init__(self, field):
        # `editAlignment` reads its alignment names off `mainwindow.field`.
        self.field = field

    def saveAllData(self):
        pass

    def seriesModified(self, modified):
        pass


def _field_stub(series, section, obj_names):
    """A real QWidget, because the dialog driver builds a real QDialog on it."""
    from PySide6.QtWidgets import QWidget
    from PyReconstruct.modules.datatypes import Trace

    class _FieldStub(QWidget):
        pass

    stub = _FieldStub()
    stub.series = series
    stub.series_states = _FakeStates()
    stub.section = section
    stub.section.selected_traces = [Trace(n, (0, 0, 0)) for n in obj_names]
    stub.table_manager = _FakeTableManager()
    stub.mainwindow = _FakeMainWindow(stub)
    return stub


class _DialogDriver:
    """Stands in for `QuickDialog` while still building the real widget.

    The point of the fix is what the combo *shows on open*, which is decided
    inside `QuickDialog`'s own combo branch -- so faking the dialog outright
    would test the assertion rather than the behavior. This builds the real
    `QuickDialog` from the structure `editAlignment` handed over, records what
    the combo actually holds, optionally picks an entry the way a user would,
    and then calls `accept(close=False)` to produce the responses. `close=False`
    is what keeps it out of a modal event loop, which under the offscreen
    platform never returns.
    """

    structure = None
    items = None
    shown = None
    pick = _UNTOUCHED

    @classmethod
    def reset(cls, pick=_UNTOUCHED):
        cls.structure = cls.items = cls.shown = None
        cls.pick = pick

    @classmethod
    def get(cls, parent, structure, title="Dialog", *args, **kwargs):
        from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog

        cls.structure = structure
        dialog = QuickDialog(parent, structure, title)
        combo = dialog.inputs[0].widget
        cls.items = [combo.itemText(i) for i in range(combo.count())]
        cls.shown = combo.currentText()
        if cls.pick is not _UNTOUCHED:
            combo.setCurrentText(cls.pick)
        if not dialog.accept(close=False):
            return None, False
        return dialog.responses, True


def _run_edit_alignment(monkeypatch, series, section, obj_names, pick=_UNTOUCHED):
    """Drive the real `editAlignment` end to end."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as mod
    from PyReconstruct.modules.gui.dialog import quick_dialog as qd

    notices = []
    # `getResponse` calls the modal `notify()` when it rejects a field. Nothing
    # here should reach it, and a test that does must fail rather than hang.
    monkeypatch.setattr(qd, "notify", lambda message, *a, **k: notices.append(message))

    _DialogDriver.reset(pick)
    monkeypatch.setattr(mod, "QuickDialog", _DialogDriver)

    stub = _field_stub(series, section, obj_names)
    mod.FieldWidgetObject.editAlignment(stub)
    assert not notices, f"the dialog rejected a field: {notices}"
    return _DialogDriver


def _seeded(driver):
    """The third element of the combo tuple, or None when there is none."""
    combo = driver.structure[0][1]
    return combo[2] if len(combo) > 2 else None


# ---------------------------------------------------------------------------
# (a) one object
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_single_object_opens_on_its_current_alignment(tmp_path, monkeypatch, qapp):
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "no-alignment")

    driver = _run_edit_alignment(monkeypatch, series, section, [obj])

    assert _seeded(driver) == "no-alignment", (
        "the combo tuple needs a third element for QuickDialog to select "
        "anything; without it `selected` is None and the blank item wins"
    )
    assert driver.shown == "no-alignment", (
        "the dialog must open showing the object's current alignment"
    )


# ---------------------------------------------------------------------------
# (b) several objects that agree
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_agreeing_selection_opens_on_the_shared_alignment(tmp_path, monkeypatch, qapp):
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj_a, "alignment", "no-alignment")
    series.setAttr(obj_b, "alignment", "no-alignment")

    driver = _run_edit_alignment(monkeypatch, series, section, [obj_a, obj_b])

    assert _seeded(driver) == "no-alignment"
    assert driver.shown == "no-alignment"


# ---------------------------------------------------------------------------
# (c) several objects that disagree -- unchanged
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_disagreeing_selection_still_opens_blank(tmp_path, monkeypatch, qapp):
    """No single value to show, so the dialog shows none. As before the fix."""
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj_a, "alignment", "default")
    series.setAttr(obj_b, "alignment", "no-alignment")

    driver = _run_edit_alignment(monkeypatch, series, section, [obj_a, obj_b])

    assert _seeded(driver) is None
    assert driver.shown == ""


@pytest.mark.gui
def test_selection_disagreeing_with_an_unset_object_opens_blank(tmp_path, monkeypatch, qapp):
    """"No override" is a value the consensus has to be able to disagree with.

    `getAttr` returns None for an object with no alignment key, so a selection
    mixing one of those with an object that has an override must not seed the
    override.
    """
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj_a, "alignment", "no-alignment")
    series.setAttr(obj_b, "alignment", None)

    driver = _run_edit_alignment(monkeypatch, series, section, [obj_a, obj_b])

    assert _seeded(driver) is None
    assert driver.shown == ""


# ---------------------------------------------------------------------------
# (d) OK on an untouched dialog
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_untouched_ok_leaves_a_real_alignment_alone(tmp_path, monkeypatch, qapp):
    """The reported bug, driven through the real command."""
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "no-alignment")

    _run_edit_alignment(monkeypatch, series, section, [obj])

    assert series.getAttr(obj, "alignment") == "no-alignment", (
        "confirming a dialog the user never touched must not clear the "
        "object's alignment"
    )


@pytest.mark.gui
def test_untouched_ok_leaves_an_agreeing_selection_alone(tmp_path, monkeypatch, qapp):
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj_a, "alignment", "no-alignment")
    series.setAttr(obj_b, "alignment", "no-alignment")

    _run_edit_alignment(monkeypatch, series, section, [obj_a, obj_b])

    assert series.getAttr(obj_a, "alignment") == "no-alignment"
    assert series.getAttr(obj_b, "alignment") == "no-alignment"


# ---------------------------------------------------------------------------
# (e) deliberately picking the blank entry -- unchanged
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_choosing_the_blank_entry_still_clears_the_override(tmp_path, monkeypatch, qapp):
    """The blank entry is the only way to say "follow the series alignment".

    Seeding the combo must not take that away, which is the whole reason the
    fix is a seed rather than a removal of the blank item.
    """
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "no-alignment")

    _run_edit_alignment(monkeypatch, series, section, [obj], pick="")

    assert series.getAttr(obj, "alignment") is None
    assert obj not in series.obj_attrs or "alignment" not in series.obj_attrs[obj]


@pytest.mark.gui
def test_blank_entry_is_offered_even_when_the_combo_is_seeded(tmp_path, monkeypatch, qapp):
    """The mechanism behind the test above: `not required` prepends the blank
    item whatever `selected` is, so the seed only moves the selection."""
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "no-alignment")

    driver = _run_edit_alignment(monkeypatch, series, section, [obj])

    assert driver.items[0] == ""
    assert set(driver.items) == {""} | set(section.tforms.keys())


@pytest.mark.gui
def test_choosing_another_alignment_still_sets_it(tmp_path, monkeypatch, qapp):
    """The ordinary use of the dialog, which the seed must not disturb."""
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj_a, "alignment", "default")
    series.setAttr(obj_b, "alignment", "default")

    _run_edit_alignment(
        monkeypatch, series, section, [obj_a, obj_b], pick="no-alignment"
    )

    assert series.getAttr(obj_a, "alignment") == "no-alignment"
    assert series.getAttr(obj_b, "alignment") == "no-alignment"


# ---------------------------------------------------------------------------
# an alignment the section no longer defines
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_a_stale_alignment_is_not_seeded(tmp_path, monkeypatch, qapp):
    """Seeding a name with no matching item would make OK unreachable.

    `InputField.getResponse` returns `(None, False)` and notifies for combo text
    that `findText` cannot resolve, so the dialog would refuse to close. Such an
    object opens blank instead, which is what it did before the fix.
    """
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "an-alignment-that-was-deleted")

    driver = _run_edit_alignment(monkeypatch, series, section, [obj])

    assert _seeded(driver) is None
    assert driver.shown == ""


# ---------------------------------------------------------------------------
# the surrounding contract
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_state_is_still_recorded_so_the_edit_stays_undoable(tmp_path, monkeypatch, qapp):
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    section = series.loadSection(sorted(series.sections.keys())[0])
    series.setAttr(obj, "alignment", "default")

    from PyReconstruct.modules.gui.main import field_widget_3_object as mod
    from PyReconstruct.modules.gui.dialog import quick_dialog as qd

    monkeypatch.setattr(qd, "notify", lambda *a, **k: None)
    _DialogDriver.reset(pick="no-alignment")
    monkeypatch.setattr(mod, "QuickDialog", _DialogDriver)

    stub = _field_stub(series, section, [obj])
    mod.FieldWidgetObject.editAlignment(stub)

    assert stub.series_states.states == 1

"""Regression tests for removing a tag from the object attributes dialog.

Bug: the object list's "Edit attributes..." dialog could not remove a tag. It
pre-filled the Tags field with the object's current tags, so deleting one and
confirming looked exactly like every other edit in that dialog, and silently did
nothing. Clearing the field entirely did nothing either. The only route to
removing a tag from an object was the separate "Remove all tags" command, which
is all-or-nothing.

Root cause: `Series.editObjectAttributes` called
`Section.editTraceAttributes(..., add_tags=True)` unconditionally. With
`add_tags=True` the consumer iterates the incoming set and adds each element, so
a set with a tag missing is indistinguishable from a set with it present, and an
empty set is an empty loop. Only the `add_tags=False` branch assigns, and only
an assignment can remove.

Why the additive call could not simply be flipped to a replacement: the same
dialog also serves a multi-object selection, where the Tags field starts blank
because there is no single value to show. Replacing on that path would set every
selected object's traces to whatever the field held, discarding tags the user was
never shown. That is the data-loss shape reported separately for the trace
dialog.

Fix: `editObjectAttributes` takes `add_tags` (default True, so no other caller
changes) and the object list decides it from whether the dialog was actually
showing the selection's tags. One object: the field held the truth, so the set
coming back is the intended final list and replaces. More than one: the field
never held the truth, so the set can only be added.

The multi-object selection therefore still cannot remove a tag through this
dialog. That is deliberate and not the bug being fixed here: the field cannot
express per-object removal for a selection whose tags it did not display.
"""
import os
import shutil
import pytest

from PyReconstruct.modules.datatypes import Trace

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _tags_on_disk(series, obj_name):
    """Every stored trace's tags for one object, read back per section."""
    out = []
    for snum, section in series.enumerateSections(show_progress=False):
        if obj_name in section.contours:
            for trace in section.contours[obj_name].getTraces():
                out.append(set(trace.tags))
    assert out, f"object {obj_name} had no traces to check"
    return out


def _set_tags(series, obj_name, tags):
    """Put a known set of tags on an object, using the replacement path."""
    series.editObjectAttributes(
        [obj_name], tags=set(tags), add_tags=False, log_event=False
    )


def _two_objects(series):
    names = sorted(series.data["objects"].keys())
    if len(names) < 2:
        pytest.skip("fixture has fewer than two objects")
    return names[0], names[1]


# ---------------------------------------------------------------------------
# the consumer: Series.editObjectAttributes
# ---------------------------------------------------------------------------
def test_replacement_removes_a_tag(tmp_path):
    """The bug, at the layer that caused it. One tag of two is dropped."""
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha", "beta"})
    assert all(t == {"alpha", "beta"} for t in _tags_on_disk(series, obj))

    series.editObjectAttributes(
        [obj], tags={"alpha"}, add_tags=False, log_event=False
    )

    assert all(t == {"alpha"} for t in _tags_on_disk(series, obj)), (
        "an edited tag set must be able to drop a tag; with add_tags=True the "
        "missing tag simply survives"
    )


def test_replacement_with_empty_set_clears_all_tags(tmp_path):
    """Clearing the field entirely. An empty set must mean "no tags"."""
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha", "beta"})

    series.editObjectAttributes(
        [obj], tags=set(), add_tags=False, log_event=False
    )

    assert all(t == set() for t in _tags_on_disk(series, obj)), (
        "an empty set is the only way to say 'clear'; under add_tags=True it "
        "is an empty loop and nothing happens"
    )


def test_default_stays_additive(tmp_path):
    """`add_tags` defaults to True, so callers that do not pass it are unchanged.

    `Object.name`'s setter and the autoseg recolor path both call
    `editObjectAttributes` without it.
    """
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha"})

    series.editObjectAttributes([obj], tags={"beta"}, log_event=False)

    assert all(t == {"alpha", "beta"} for t in _tags_on_disk(series, obj))


def test_additive_preserves_divergent_tags_across_objects(tmp_path):
    """The property the multi-object path depends on.

    Two objects with different tags, one shared tag added: neither loses what it
    had. This is what makes it safe to leave a multi-object edit additive.
    """
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    _set_tags(series, obj_a, {"only_a"})
    _set_tags(series, obj_b, {"only_b"})

    series.editObjectAttributes(
        [obj_a, obj_b], tags={"shared"}, add_tags=True, log_event=False
    )

    assert all(t == {"only_a", "shared"} for t in _tags_on_disk(series, obj_a))
    assert all(t == {"only_b", "shared"} for t in _tags_on_disk(series, obj_b))


def test_none_leaves_tags_alone_under_either_flag(tmp_path):
    """None means "no value chosen" for tags exactly as it does for name/color.

    The trace dialog returns None for a selection whose tags disagree, so this
    has to hold on the replacement path too.
    """
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha"})

    series.editObjectAttributes(
        [obj], color=(9, 9, 9), tags=None, add_tags=False, log_event=False
    )
    assert all(t == {"alpha"} for t in _tags_on_disk(series, obj))

    series.editObjectAttributes(
        [obj], color=(8, 8, 8), tags=None, add_tags=True, log_event=False
    )
    assert all(t == {"alpha"} for t in _tags_on_disk(series, obj))


# ---------------------------------------------------------------------------
# the producer: the object list's "Edit attributes..." command
# ---------------------------------------------------------------------------
class _FakeTraceDialog:
    """Stands in for `TraceDialog`, recording what it was shown.

    The real dialog needs a modal event loop and a QWidget parent. What matters
    here is the contract either side of it: which tags the object list hands the
    dialog, and what it does with the set the dialog hands back.
    """

    seen = None      # kwargs the object list constructed it with
    returns = None   # (tags, sections) to report as the user's input

    def __init__(self, parent, **kwargs):
        type(self).seen = kwargs

    def exec(self):
        tags, sections = type(self).returns
        trace = Trace(None, None)
        trace.color = None
        trace.tags = tags
        trace.fill_mode = (None, None)
        return (trace, sections), True


class _FakeTable:
    def hasFocus(self):
        # Not an ObjectTableWidget, so object_function falls back to the
        # selected traces in the field for the selection.
        return None

    def updateObjects(self, names):
        pass


class _FakeMainWindow:
    def saveAllData(self):
        pass

    def seriesModified(self, modified):
        pass


class _FakeSection:
    def __init__(self, obj_names):
        self.selected_traces = [Trace(n, (0, 0, 0)) for n in obj_names]


class _FieldStub:
    """The minimum `FieldWidgetObject.editAttributes` and its decorator touch."""

    def __init__(self, series, obj_names):
        self.series = series
        self.series_states = None
        self.section = _FakeSection(obj_names)
        self.table_manager = _FakeTable()
        self.mainwindow = _FakeMainWindow()

    def reload(self):
        pass


def _run_edit_attributes(monkeypatch, series, obj_names, returns):
    """Drive the real `editAttributes` with the dialog faked out."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as mod

    _FakeTraceDialog.seen = None
    _FakeTraceDialog.returns = returns
    monkeypatch.setattr(mod, "TraceDialog", _FakeTraceDialog)

    stub = _FieldStub(series, obj_names)
    mod.FieldWidgetObject.editAttributes(stub)
    return _FakeTraceDialog.seen


@pytest.mark.gui
def test_single_object_edit_can_clear_tags(tmp_path, monkeypatch):
    """The reported symptom, driven through the real command.

    One object selected, its tags shown, the user empties the field. Before the
    fix the tags survived.
    """
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha", "beta"})

    seen = _run_edit_attributes(
        monkeypatch, series, [obj], returns=(set(), None)
    )

    assert seen["tags"] == {"alpha", "beta"}, (
        "the dialog must be pre-filled with the object's tags; that is why the "
        "set it returns can be read as a replacement"
    )
    assert all(t == set() for t in _tags_on_disk(series, obj)), (
        "emptying the Tags field on a single-object selection must remove the "
        "tags"
    )


@pytest.mark.gui
def test_single_object_edit_can_drop_one_tag(tmp_path, monkeypatch):
    """The everyday case: delete one row of the Tags field, keep the rest."""
    series = _load_series(tmp_path)
    obj, _ = _two_objects(series)
    _set_tags(series, obj, {"alpha", "beta"})

    _run_edit_attributes(monkeypatch, series, [obj], returns=({"alpha"}, None))

    assert all(t == {"alpha"} for t in _tags_on_disk(series, obj))


@pytest.mark.gui
def test_multi_object_edit_adds_without_erasing(tmp_path, monkeypatch):
    """The other half of the fix, and the reason it is not a blanket flip.

    Two objects with different tags. The dialog shows a blank Tags field because
    there is no single value to show, the user types one tag, and both objects
    keep what they had.
    """
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    _set_tags(series, obj_a, {"only_a"})
    _set_tags(series, obj_b, {"only_b"})

    seen = _run_edit_attributes(
        monkeypatch, series, [obj_a, obj_b], returns=({"shared"}, None)
    )

    assert seen["tags"] is None, (
        "a multi-object selection has no single tag set to display"
    )
    assert all(t == {"only_a", "shared"} for t in _tags_on_disk(series, obj_a))
    assert all(t == {"only_b", "shared"} for t in _tags_on_disk(series, obj_b))


@pytest.mark.gui
def test_multi_object_edit_with_blank_field_changes_nothing(tmp_path, monkeypatch):
    """Confirming a multi-object edit without touching the Tags field.

    The dialog reports either an empty set or None here depending on how it
    resolves an untouched blank field. Neither may remove a tag, since the user
    was never shown one.
    """
    series = _load_series(tmp_path)
    obj_a, obj_b = _two_objects(series)
    _set_tags(series, obj_a, {"only_a"})
    _set_tags(series, obj_b, {"only_b"})

    for blank in (set(), None):
        _run_edit_attributes(
            monkeypatch, series, [obj_a, obj_b], returns=(blank, None)
        )
        assert all(t == {"only_a"} for t in _tags_on_disk(series, obj_a)), blank
        assert all(t == {"only_b"} for t in _tags_on_disk(series, obj_b)), blank

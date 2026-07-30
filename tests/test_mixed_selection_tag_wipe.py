"""Regression tests for tag loss when the trace dialog opens on a mixed selection.

Bug: OK'ing the trace attributes dialog on a multi-trace selection whose tags
disagree erased the tags of every selected trace, with no warning and no
opportunity to notice. Reachable on stock behavior by selecting two traces with
different tags and confirming the dialog, even without touching the tags field.

Root cause, a sentinel mismatch across the dialog boundary:

- ``TraceDialog.__init__`` folds a disagreeing selection down to a single
  displayed value per field. For name it uses ``"*"``; for ``color``, ``points``
  and both halves of ``fill_mode`` it uses ``None``. For tags it used an EMPTY
  SET.
- ``Section.editTraceAttributes`` treats ``None`` as "leave this attribute
  alone" (``if tags is not None:``) and an empty set as a real value, so it took
  the replace branch and assigned the empty set to every trace.

The empty set could not simply be swapped for ``None``, for two reasons:

1. An empty set is the legitimate way to say "clear all tags", and
   ``Series.removeAllTraceTags`` calls ``editTraceAttributes(tags=set())`` for
   exactly that. Changing the meaning of the empty set at the consumer would
   break the object list's "Remove all trace tags" command.
2. The dialog's return value is not the constructor's ``tags`` argument. It is
   ``set(self.tags_input.getEntries())``, read back off the widget. ``MultiInput``
   renders both ``None`` and an empty set as a single blank row and
   ``getEntries()`` drops blanks, so the widget cannot carry the distinction and
   editing the constructor alone would not have changed the returned value.

Fix: ``TraceDialog`` records ``tags_mixed`` when it blanks the field for lack of
a single value, and ``exec()`` returns ``None`` instead of an empty set when the
field is still blank on confirm. A blank field the user actually emptied is
unaffected, because ``tags_mixed`` is False whenever the selection agreed.

The two intents remain distinguishable everywhere it matters: mixedness is known
at construction time, so "user cleared a populated field" (agreeing selection)
and "field was never populated" (disagreeing selection) are separate states. The
one case they still collapse is clearing all tags on a selection that disagrees,
where the field starts blank and staying blank has to mean one thing or the
other. It resolves to the non-destructive reading here. See the module-level
note in the last test.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.section import Section


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _trace(name, tags):
    t = Trace(name, (255, 0, 0))
    t.points = [(0, 0), (1, 0), (1, 1)]
    t.tags = set(tags)
    return t


def _bare_section():
    """A Section with no backing files.

    ``Section.__init__`` reads its section file off disk, so it cannot be
    constructed here. ``editTraceAttributes`` touches only ``contours``, the
    tracking lists and ``selected_traces`` once ``log_event=False`` rules out the
    log call, which is the same approach ``test_section_contour.py`` takes.
    """
    section = Section.__new__(Section)
    section.n = 0
    section.contours = {}
    section.added_traces = []
    section.removed_traces = []
    section.selected_traces = []
    return section


def _dialog(qapp, monkeypatch, traces=None, **kwargs):
    """A real TraceDialog whose modal event loop is stubbed out as accepted.

    ``TraceDialog.exec`` calls ``super().exec()`` first. Offscreen Qt has no one
    to dismiss a modal, so the real one never returns; patch QDialog.exec to
    report "the user pressed OK" and let the rest of the method run for real.
    """
    from PySide6.QtWidgets import QDialog, QWidget
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    parent = QWidget()
    dialog = TraceDialog(parent, traces if traces is not None else [], **kwargs)
    return dialog, parent


def _set_entries(dialog, values):
    """Type `values` into the tags widget, the way a user would."""
    widget = dialog.tags_input
    while len(widget.inputs) < len(values):
        widget.add()
    for line_edit, value in zip(widget.inputs, values):
        line_edit.setText(value)
    for line_edit in widget.inputs[len(values):]:
        line_edit.setText("")


# ---------------------------------------------------------------------------
# the dialog boundary
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_mixed_tags_untouched_returns_none_not_empty_set(qapp, monkeypatch):
    """The bug. Disagreeing tags plus an untouched field must not mean "clear"."""
    traces = [_trace("a", {"x"}), _trace("a", {"y"})]
    dialog, parent = _dialog(qapp, monkeypatch, traces)
    try:
        assert dialog.tags_mixed is True
        result, confirmed = dialog.exec()
        assert confirmed is True
        assert result.tags is None, (
            "a disagreeing selection must report 'no value chosen' as None; an "
            "empty set makes editTraceAttributes erase every trace's tags"
        )
    finally:
        parent.deleteLater()


@pytest.mark.gui
def test_agreeing_selection_cleared_by_user_returns_empty_set(qapp, monkeypatch):
    """The deliberate-clear path, multi-trace. Must still clear."""
    traces = [_trace("a", {"x"}), _trace("a", {"x"})]
    dialog, parent = _dialog(qapp, monkeypatch, traces)
    try:
        assert dialog.tags_mixed is False
        _set_entries(dialog, [])  # user empties the field
        result, confirmed = dialog.exec()
        assert confirmed is True
        assert result.tags == set(), (
            "clearing a field that showed real tags is a deliberate clear and "
            "must stay expressible"
        )
    finally:
        parent.deleteLater()


@pytest.mark.gui
def test_single_trace_cleared_by_user_returns_empty_set(qapp, monkeypatch):
    """The deliberate-clear path, single trace."""
    dialog, parent = _dialog(qapp, monkeypatch, [_trace("a", {"x", "y"})])
    try:
        assert dialog.tags_mixed is False
        _set_entries(dialog, [])
        result, confirmed = dialog.exec()
        assert confirmed is True
        assert result.tags == set()
    finally:
        parent.deleteLater()


@pytest.mark.gui
def test_mixed_selection_with_typed_tags_still_replaces(qapp, monkeypatch):
    """Mixedness must not make the field read-only: a typed value still applies."""
    traces = [_trace("a", {"x"}), _trace("a", {"y"})]
    dialog, parent = _dialog(qapp, monkeypatch, traces)
    try:
        _set_entries(dialog, ["z"])
        result, confirmed = dialog.exec()
        assert confirmed is True
        assert result.tags == {"z"}
    finally:
        parent.deleteLater()


@pytest.mark.gui
def test_multi_object_selection_reports_mixed(qapp, monkeypatch):
    """The object list passes tags=None with no traces for a multi-object edit.

    Same "no single value" case, reached through the ``else`` branch of the
    constructor rather than the comparison loop.
    """
    dialog, parent = _dialog(qapp, monkeypatch, [], tags=None, is_obj_list=False)
    try:
        assert dialog.tags_mixed is True
        result, confirmed = dialog.exec()
        assert result.tags is None
    finally:
        parent.deleteLater()


@pytest.mark.gui
def test_single_object_with_no_tags_is_not_mixed(qapp, monkeypatch):
    """An object that genuinely has no tags is not "mixed".

    ``series.data.getTags`` returns an empty set for an untagged object, and the
    dialog must keep that distinct from None so the user can still clear.
    """
    dialog, parent = _dialog(qapp, monkeypatch, [], name="obj", tags=set())
    try:
        assert dialog.tags_mixed is False
        result, confirmed = dialog.exec()
        assert result.tags == set()
    finally:
        parent.deleteLater()


# ---------------------------------------------------------------------------
# end to end: the reported data loss
# ---------------------------------------------------------------------------
@pytest.mark.gui
def test_confirming_dialog_on_mixed_selection_does_not_erase_tags(qapp, monkeypatch):
    """The reported symptom, dialog through to the stored traces.

    Drives the dialog's return value into ``editTraceAttributes`` the way
    ``FieldWidget.traceDialog`` does, so this fails on the erasure itself rather
    than on the absence of an internal flag.
    """
    section = _bare_section()
    section.addTrace(_trace("a", {"x"}), log_event=False)
    section.addTrace(_trace("a", {"y"}), log_event=False)
    traces = section.contours["a"].getTraces()

    dialog, parent = _dialog(qapp, monkeypatch, traces)
    try:
        result, confirmed = dialog.exec()
    finally:
        parent.deleteLater()
    assert confirmed is True

    # exactly what FieldWidget.traceDialog does with the response
    section.editTraceAttributes(
        traces=traces.copy(),
        name=result.name, color=result.color,
        tags=result.tags, mode=result.fill_mode,
        log_event=False,
    )

    surviving = sorted(sorted(t.tags) for t in section.contours["a"].getTraces())
    assert surviving == [["x"], ["y"]], (
        "confirming the dialog without touching the tags field erased the tags "
        "of every selected trace"
    )


# ---------------------------------------------------------------------------
# the consumer contract the fix relies on
# ---------------------------------------------------------------------------
def test_editTraceAttributes_none_preserves_each_traces_own_tags():
    """None must leave per-trace tags alone, including when they differ."""
    section = _bare_section()
    a, b = _trace("a", {"x"}), _trace("a", {"y"})
    section.addTrace(a, log_event=False)
    section.addTrace(b, log_event=False)

    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=(0, 255, 0), tags=None, mode=None, log_event=False,
    )

    tags = sorted(sorted(t.tags) for t in section.contours["a"].getTraces())
    assert tags == [["x"], ["y"]]


def test_editTraceAttributes_empty_set_still_clears():
    """The empty set must keep meaning "clear".

    Series.removeAllTraceTags calls editTraceAttributes(tags=set()) with the
    default add_tags=False for exactly this. The fix deliberately did not touch
    the consumer's reading of the empty set, and this pins that.
    """
    section = _bare_section()
    a, b = _trace("a", {"x"}), _trace("a", {"y"})
    section.addTrace(a, log_event=False)
    section.addTrace(b, log_event=False)

    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=None, tags=set(), mode=None, log_event=False,
    )

    assert all(t.tags == set() for t in section.contours["a"].getTraces())

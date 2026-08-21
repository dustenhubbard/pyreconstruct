"""Regression tests for the sentinel-mismatch bug class.

The class: a producer encodes "this selection has no single value" as an empty
collection or an empty string, and a consumer reads that same value as "replace
what is there with nothing". The two known instances were the trace attributes
dialog wiping tags on a mixed selection, and ``Series.editObjectAttributes``
treating ``sections=None`` as an empty container.

The instances covered here were found by an AST audit of the whole package and
are the only two confirmed reachable ones outside the known pair, plus one
keyword mismatch found alongside them:

* ``FieldWidgetObject.editComment`` blanks the comment field whenever more than
  one object is selected, and then writes the field back onto every selected
  object unconditionally.
* ``FieldWidgetObject.edit3D`` guards the ``3D_opacity`` write with
  ``is not None`` and then calls ``SceneObject.setAlpha`` with the same value
  unguarded.
* The "Merge attributes only" context-menu actions pass ``merge_attrs=True`` to
  ``mergeTraces``, whose keyword is ``merge_attrs_only``.

Every test drives the real decorated method through ``object_function``'s
wrapper on a duck-typed stub, which is the pattern established by
``test_modify_selected_scale_cubes.py``. Driving the wrapper rather than the
inner function also proves the path is the one the context menu reaches.
"""

import inspect
import types

import pytest

from PyReconstruct.modules.gui.main import field_widget_3_object as fw3
from PyReconstruct.modules.gui.main import context_menu_list as cml
from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------

class _Series:
    """The slice of Series that these two object functions reach for."""

    def __init__(self, attrs):
        self.attrs = attrs          # {obj_name: {attr: value}}
        self.logs = []
        self.jser_fp = "/tmp/stub.jser"

    def getAttr(self, name, attr_name, ztrace=False):
        if name in self.attrs and attr_name in self.attrs[name]:
            return self.attrs[name][attr_name]
        # the real defaults, from Series.getAttr
        return {
            "3D_mode": "surface",
            "3D_opacity": 1,
            "comment": "",
            "locked": False,
        }.get(attr_name)

    def setAttr(self, name, attr_name, value, ztrace=False):
        self.attrs.setdefault(name, {})[attr_name] = value

    def addLog(self, *a, **k):
        self.logs.append(a)


class _SceneObject:
    def __init__(self):
        self.alpha_calls = []

    def setAlpha(self, new_alpha, series=None):
        self.alpha_calls.append(new_alpha)


def _field(series, viewer=None):
    """A stub carrying only what object_function's wrapper and these two
    methods touch. reload_field is False for both, so no reload is needed."""
    states = types.SimpleNamespace(calls=0)
    states.addState = lambda *a, **k: setattr(states, "calls", states.calls + 1)
    return types.SimpleNamespace(
        series=series,
        series_states=states,
        # not an ObjectTableWidget, so the wrapper falls back to the field
        table_manager=types.SimpleNamespace(
            hasFocus=lambda: None,
            updateObjects=lambda names: None,
            refresh=lambda: None,
        ),
        section=types.SimpleNamespace(selected_traces=[]),
        mainwindow=types.SimpleNamespace(
            saveAllData=lambda: None,
            seriesModified=lambda b: None,
            viewer=viewer,
        ),
    )


def _select(field, names):
    field.section.selected_traces = [types.SimpleNamespace(name=n) for n in names]


# ---------------------------------------------------------------------------
# editComment
# ---------------------------------------------------------------------------

def _patch_input(monkeypatch, captured, returns):
    def getText(parent, title, label, text=""):
        captured["text"] = text
        return returns

    monkeypatch.setattr(fw3, "QInputDialog", types.SimpleNamespace(getText=getText))


def test_shared_comment_is_shown_for_a_multi_selection(monkeypatch):
    """Two objects that agree still have a single value to display."""
    captured = {}
    _patch_input(monkeypatch, captured, ("check me", True))
    series = _Series({"a": {"comment": "check me"}, "b": {"comment": "check me"}})
    field = _field(series)
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.editComment(field)

    assert captured["text"] == "check me"


def test_ok_on_an_untouched_shared_comment_keeps_it(monkeypatch):
    """The whole bug: the field was blanked on selection size alone, so OK
    erased a comment the two objects agreed on and never displayed."""
    captured = {}

    # echo whatever the dialog was seeded with, i.e. the user pressed OK
    def getText(parent, title, label, text=""):
        captured["text"] = text
        return text, True

    monkeypatch.setattr(fw3, "QInputDialog", types.SimpleNamespace(getText=getText))

    series = _Series({"a": {"comment": "check me"}, "b": {"comment": "check me"}})
    field = _field(series)
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.editComment(field)

    assert series.getAttr("a", "comment") == "check me"
    assert series.getAttr("b", "comment") == "check me"


def test_clearing_a_shared_comment_still_clears_every_object(monkeypatch):
    """The selection agreed, so the field showed the value and blanking it is a
    deliberate bulk clear. That has to keep working."""
    _patch_input(monkeypatch, {}, ("", True))
    series = _Series({"a": {"comment": "check me"}, "b": {"comment": "check me"}})
    field = _field(series)
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.editComment(field)

    assert series.getAttr("a", "comment") == ""
    assert series.getAttr("b", "comment") == ""


def test_blank_ok_does_not_wipe_comments_that_disagree(monkeypatch):
    """No single value to display, so a blank field means "nothing chosen"."""
    captured = {}
    _patch_input(monkeypatch, captured, ("", True))
    series = _Series({"a": {"comment": "one"}, "b": {"comment": "two"}})
    field = _field(series)
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.editComment(field)

    assert captured["text"] == "", "a disagreeing selection has nothing to show"
    assert series.getAttr("a", "comment") == "one"
    assert series.getAttr("b", "comment") == "two"


def test_a_single_object_can_still_have_its_comment_cleared(monkeypatch):
    """Blanking one object's comment is a real edit and must keep working."""
    _patch_input(monkeypatch, {}, ("", True))
    series = _Series({"a": {"comment": "check me"}})
    field = _field(series)
    _select(field, ["a"])

    fw3.FieldWidgetObject.editComment(field)

    assert series.getAttr("a", "comment") == ""


def test_a_typed_comment_reaches_every_selected_object(monkeypatch):
    _patch_input(monkeypatch, {}, ("new note", True))
    series = _Series({"a": {"comment": "one"}, "b": {"comment": "two"}})
    field = _field(series)
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.editComment(field)

    assert series.getAttr("a", "comment") == "new note"
    assert series.getAttr("b", "comment") == "new note"


def test_cancel_writes_nothing(monkeypatch):
    _patch_input(monkeypatch, {}, ("wiped", False))
    series = _Series({"a": {"comment": "one"}})
    field = _field(series)
    _select(field, ["a"])

    fw3.FieldWidgetObject.editComment(field)

    assert series.getAttr("a", "comment") == "one"


# ---------------------------------------------------------------------------
# edit3D
# ---------------------------------------------------------------------------

def _patch_quick(monkeypatch, captured, returns):
    def get(parent, structure, *a, **k):
        captured["structure"] = structure
        return returns

    monkeypatch.setattr(fw3, "QuickDialog", types.SimpleNamespace(get=get))


def _viewer(scene_obj):
    return types.SimpleNamespace(
        plt=types.SimpleNamespace(
            objs=types.SimpleNamespace(search=lambda name, t, fp: scene_obj)
        )
    )


def test_blank_opacity_does_not_poison_the_scene_alpha(monkeypatch):
    """A blank opacity field is "no value chosen". The sibling setAttr already
    reads it that way; setAlpha did not, and stored None on the mesh, which
    then made the opacity-increment shortcut raise on None + i."""
    scene_obj = _SceneObject()
    _patch_quick(monkeypatch, {}, (["surface", None], True))
    series = _Series({"a": {"3D_opacity": 0.4}, "b": {"3D_opacity": 0.9}})
    field = _field(series, viewer=_viewer(scene_obj))
    _select(field, ["a", "b"])

    fw3.FieldWidgetObject.edit3D(field)

    assert None not in scene_obj.alpha_calls
    assert series.getAttr("a", "3D_opacity") == 0.4
    assert series.getAttr("b", "3D_opacity") == 0.9


def test_zero_opacity_still_reaches_the_scene(monkeypatch):
    """0.0 is a legal opacity, so the guard has to be `is not None` and not a
    truthiness test."""
    scene_obj = _SceneObject()
    _patch_quick(monkeypatch, {}, (["surface", 0.0], True))
    series = _Series({"a": {"3D_opacity": 0.4}})
    field = _field(series, viewer=_viewer(scene_obj))
    _select(field, ["a"])

    fw3.FieldWidgetObject.edit3D(field)

    assert scene_obj.alpha_calls == [0.0]
    assert series.getAttr("a", "3D_opacity") == 0.0


def test_a_chosen_opacity_reaches_the_scene(monkeypatch):
    scene_obj = _SceneObject()
    _patch_quick(monkeypatch, {}, (["spheres", 0.25], True))
    series = _Series({"a": {"3D_opacity": 0.4}})
    field = _field(series, viewer=_viewer(scene_obj))
    _select(field, ["a"])

    fw3.FieldWidgetObject.edit3D(field)

    assert scene_obj.alpha_calls == [0.25]
    assert series.getAttr("a", "3D_mode") == "spheres"


# ---------------------------------------------------------------------------
# "Merge attributes only"
# ---------------------------------------------------------------------------

def _trace_field(recorded):
    """A stub carrying the handlers both trace-menu builders bind."""
    noop = lambda *a, **k: None
    return types.SimpleNamespace(
        series="sc",
        mergeTraces=lambda *a, **k: recorded.update(k),
        hideTraces=noop,
        hideOtherTraces=noop,
        traceDialog=noop,
        smoothTraces=noop,
        makeNegative=noop,
        closeTraces=noop,
        editTraceRadius=noop,
        editTraceShape=noop,
        copyTracesToSections=noop,
        createTraceFlag=noop,
        deleteTraces=noop,
    )


@pytest.mark.parametrize(
    "builder",
    [
        # the field's trace submenu (the stable line keeps upstream's
        # organization, so the row lives here rather than on a top strip)
        lambda field: cml.get_context_menu_list_trace(field, is_in_field=True),
        # the trace list's own copy of the same action
        lambda field: cml.get_context_menu_list_trace(field, is_in_field=False),
    ],
    ids=["field_trace_menu", "trace_list"],
)
def test_merge_attributes_only_action_uses_the_real_keyword(builder):
    """The action passed merge_attrs=True, but the keyword is
    merge_attrs_only, so invoking it raised TypeError before any merge ran."""
    recorded = {}
    entries = builder(_trace_field(recorded))

    handler = None
    for entry in entries:
        if isinstance(entry, tuple) and entry and entry[0] == "mergeobjects_act":
            handler = entry[-1]
            break

    assert handler is not None, "mergeobjects_act not found in the menu"
    handler()
    assert recorded == {"merge_attrs_only": True}


def test_merge_traces_accepts_the_keyword_the_menu_sends():
    """``trace_function``'s wrapper is ``(*args, **kwargs)``, so a wrong keyword
    survives the wrapper and only raises inside the method. That is why the
    typo went unnoticed, and why the check has to reach the real parameters."""
    # mergeTraces carries two stacked decorators, so peel wrappers until the
    # real function is reached. Search the closure for the function rather than
    # indexing it: cells follow `co_freevars`, which is alphabetical, so a
    # decorator that closes over anything besides the wrapped function moves the
    # one being looked for off cell 0.
    inner = FieldWidgetTrace.mergeTraces
    while inner.__name__ != "mergeTraces":
        inner = next(
            cell.cell_contents for cell in inner.__closure__
            if inspect.isfunction(cell.cell_contents)
        )

    params = inspect.signature(inner).parameters
    assert "merge_attrs_only" in params
    assert "merge_attrs" not in params

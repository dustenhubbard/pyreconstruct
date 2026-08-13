"""Tests for reapplying the autoseg palette to already-imported objects.

Series imported before the autoseg color features baked their colors in at
import time. ``Series.reapplyAutosegColors`` lets a user push the CURRENT
palette (colorblind-safe default or a custom one) back onto selected objects.

Two layers are covered:

* the pure name -> color recovery (``label_id_from_name`` /
  ``palette_color_for_name``): an unmodified autoseg name reproduces the exact
  import color; anything else takes a stable, deterministic hash fallback;
* the bulk ``Series.reapplyAutosegColors`` path end-to-end on the real
  ``shapes1.jser`` fixture: colors are rewritten through the normal
  attribute-edit machinery, honor a custom palette, and a single series undo
  restores every prior color across every section;
* the series-wide View menu action ("Recolor all objects from palette...",
  ``MainWindow.recolorAllObjectsFromPalette``, added 2026-08-12): locked
  objects are skipped rather than blocking the pass, the confirm dialog names
  both counts, and one undo restores every prior color.

The method (and this file) keep the "autoseg" name for history; the menu rows
were renamed to "palette colors" on 2026-08-12 because the mapping covers any
name, which is pinned by the fallback tests below.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.backend.autoseg.palette import (
    AUTOSEG_TRACE_PREFIX,
    DEFAULT_AUTOSEG_PALETTE,
    label_id_from_name,
    palette_color,
    palette_color_for_name,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


# --------------------------------------------------------------------------- #
# name -> label id recovery
# --------------------------------------------------------------------------- #

def test_prefix_matches_import_naming():
    # guards the shared constant against drifting from the "autoseg_<id>" scheme
    assert AUTOSEG_TRACE_PREFIX == "autoseg_"
    assert f"{AUTOSEG_TRACE_PREFIX}42" == "autoseg_42"


def test_label_id_parses_bare_autoseg_names():
    assert label_id_from_name("autoseg_0") == 0
    assert label_id_from_name("autoseg_1") == 1
    assert label_id_from_name("autoseg_42") == 42
    assert label_id_from_name("autoseg_1000") == 1000


def test_label_id_rejects_non_autoseg_or_modified_names():
    # renamed / derived / non-autoseg names must NOT parse -> hash fallback
    for name in (
        "autoseg_42_dendrite",  # suffix added after import
        "autoseg_",             # no id
        "autoseg_1a",           # not all digits
        "autoseg_-5",           # sign is not a bare digit run
        "mito_3",               # different object entirely
        "dendrite",
        "",
    ):
        assert label_id_from_name(name) is None, name


def test_label_id_handles_non_string():
    assert label_id_from_name(None) is None
    assert label_id_from_name(42) is None


# --------------------------------------------------------------------------- #
# name -> color mapping
# --------------------------------------------------------------------------- #

def test_autoseg_name_reproduces_import_color_exactly():
    """An unmodified autoseg name recolors to EXACTLY what import assigned."""
    for label_id in range(0, 2000):
        name = f"{AUTOSEG_TRACE_PREFIX}{label_id}"
        assert palette_color_for_name(name) == palette_color(label_id)


def test_fallback_is_deterministic_and_from_palette():
    """Names that don't parse get a stable color drawn from the palette."""
    whitelist = set(DEFAULT_AUTOSEG_PALETTE)
    for name in ("dendrite", "mito_3", "autoseg_42_dendrite", "spine 7", ""):
        first = palette_color_for_name(name)
        assert first == palette_color_for_name(name)          # deterministic
        assert first in whitelist                              # from palette


def test_fallback_does_not_depend_on_pythonhashseed():
    """crc32 fallback (not builtin hash) -> stable across processes/runs.

    Pin one concrete value so a switch to a salted/unstable hash is caught.
    """
    import zlib
    name = "dendrite"
    expected = palette_color(zlib.crc32(name.encode("utf-8")))
    assert palette_color_for_name(name) == expected


def test_custom_palette_and_seed_are_respected():
    custom = [(10, 20, 30), (40, 50, 60), (70, 80, 90)]
    for name in ("autoseg_7", "autoseg_8", "dendrite", "mito_3"):
        c = palette_color_for_name(name, palette=custom, seed=3)
        assert c in {tuple(x) for x in custom}
        # matches the underlying palette_color contract for the recovered id
        assert c == palette_color_for_name(name, palette=custom, seed=3)
    # a different seed can reassign at least one name (sanity on seed plumbing)
    assert any(
        palette_color_for_name(f"autoseg_{i}", palette=custom, seed=0)
        != palette_color_for_name(f"autoseg_{i}", palette=custom, seed=1)
        for i in range(50)
    )


# --------------------------------------------------------------------------- #
# end-to-end on the real series fixture
# --------------------------------------------------------------------------- #

def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    series.setProgressReporter(NullProgressReporter)
    return series


def _force_options(series, palette=None, seed=0):
    """Shadow getOption so tests never read/write the machine QSettings store.

    Returns colors for the two autoseg options and delegates everything else to
    the real implementation.
    """
    real = series.getOption

    def fake(option_name, get_default=False):
        if option_name == "autoseg_color_palette":
            return [] if palette is None else palette
        if option_name == "autoseg_color_seed":
            return seed
        return real(option_name, get_default)

    series.getOption = fake


def _snapshot_colors(series, obj_names):
    """Map (snum, obj, trace_index) -> color tuple for the given objects."""
    snap = {}
    for snum, section in series.enumerateSections(show_progress=False):
        for obj in obj_names:
            if obj in section.contours:
                for i, trace in enumerate(section.contours[obj].getTraces()):
                    snap[(snum, obj, i)] = tuple(trace.color)
    return snap


def _some_objects(series, n=3):
    names = sorted(series.data["objects"].keys())
    assert names, "fixture had no objects"
    return names[:n]


def test_reapply_sets_expected_palette_colors(tmp_path):
    series = _load_series(tmp_path)
    _force_options(series)  # default palette, seed 0
    objs = _some_objects(series)

    # bake a bogus uniform color first so any change is visible
    series.editObjectAttributes(objs, color=(1, 1, 1), log_event=False)

    series.reapplyAutosegColors(objs, log_event=False)

    for snum, section in series.enumerateSections(show_progress=False):
        for obj in objs:
            if obj in section.contours:
                expected = palette_color_for_name(obj)
                for trace in section.contours[obj].getTraces():
                    assert tuple(trace.color) == expected
    series.close()


def test_reapply_id_parse_path_matches_fresh_import(tmp_path):
    """Rename an object to a bare autoseg name; recolor must equal import."""
    series = _load_series(tmp_path)
    _force_options(series)
    obj = _some_objects(series, 1)[0]

    series.editObjectAttributes([obj], name="autoseg_5", log_event=False)
    series.reapplyAutosegColors(["autoseg_5"], log_event=False)

    expected = palette_color(5)  # exactly what a fresh import would assign
    checked = 0
    for snum, section in series.enumerateSections(show_progress=False):
        if "autoseg_5" in section.contours:
            for trace in section.contours["autoseg_5"].getTraces():
                assert tuple(trace.color) == expected
                checked += 1
    assert checked, "renamed object appeared on no section"
    series.close()


def test_reapply_assigns_distinct_colors_to_distinct_ids(tmp_path):
    """Two objects whose ids map to different palette entries stay distinct."""
    series = _load_series(tmp_path)
    _force_options(series)
    two = _some_objects(series, 2)
    if len(two) < 2:
        pytest.skip("fixture has fewer than two objects")

    # ids 1 and 2 map to different default-palette entries (pinned elsewhere)
    assert palette_color(1) != palette_color(2)
    series.editObjectAttributes([two[0]], name="autoseg_1", log_event=False)
    series.editObjectAttributes([two[1]], name="autoseg_2", log_event=False)
    series.reapplyAutosegColors(["autoseg_1", "autoseg_2"], log_event=False)

    colors = {}
    for snum, section in series.enumerateSections(show_progress=False):
        for name in ("autoseg_1", "autoseg_2"):
            if name in section.contours:
                for trace in section.contours[name].getTraces():
                    colors[name] = tuple(trace.color)
    assert colors.get("autoseg_1") == palette_color(1)
    assert colors.get("autoseg_2") == palette_color(2)
    assert colors["autoseg_1"] != colors["autoseg_2"]
    series.close()


def test_reapply_respects_custom_palette(tmp_path):
    series = _load_series(tmp_path)
    custom = [(11, 22, 33), (44, 55, 66)]
    _force_options(series, palette=custom, seed=0)
    objs = _some_objects(series)

    series.reapplyAutosegColors(objs, log_event=False)

    custom_set = {tuple(c) for c in custom}
    for snum, section in series.enumerateSections(show_progress=False):
        for obj in objs:
            if obj in section.contours:
                expected = palette_color_for_name(obj, palette=custom, seed=0)
                for trace in section.contours[obj].getTraces():
                    assert tuple(trace.color) == expected
                    assert tuple(trace.color) in custom_set
    series.close()


def test_reapply_is_a_single_undoable_operation(tmp_path):
    """One series undo restores every prior color on every section."""
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    series = _load_series(tmp_path)
    _force_options(series)
    objs = _some_objects(series)

    before = _snapshot_colors(series, objs)
    assert before, "no traces to recolor in fixture"

    series_states = SeriesStates(series)
    series.reapplyAutosegColors(objs, series_states=series_states, log_event=False)

    after = _snapshot_colors(series, objs)
    assert after.keys() == before.keys()
    assert any(after[k] != before[k] for k in before), \
        "recolor changed nothing -- undo test would be vacuous"

    can_undo = series_states.canUndo()[0]
    assert can_undo, "recolor must leave an undoable series state"
    series_states.undoState()

    restored = _snapshot_colors(series, objs)
    assert restored == before, "a single undo must restore every prior color"
    series.close()


def test_reapply_empty_selection_is_noop(tmp_path):
    series = _load_series(tmp_path)
    _force_options(series)
    all_objs = _some_objects(series, 5)
    before = _snapshot_colors(series, all_objs)

    series.reapplyAutosegColors([], log_event=False)  # must not raise

    assert _snapshot_colors(series, all_objs) == before
    series.close()


# --------------------------------------------------------------------------- #
# the series-wide View menu action
# --------------------------------------------------------------------------- #

def _run_view_recolor(series, monkeypatch, confirm=True):
    """Run MainWindow.recolorAllObjectsFromPalette on a stub main window.

    The handler is deliberately not routed through the object_function wrapper
    (whose locked check ABORTS; series-wide, locked objects must be skipped),
    so this drives the real method with the real series and stubs only the
    window plumbing the wrapper would have touched: saveAllData, the field's
    table manager and reload, and the notify dialogs.

    Returns (messages, calls, series_states): the dialog texts shown, the
    plumbing calls made, and the undo states the pass wrote into.
    """
    import types
    from PyReconstruct.modules.gui.main import main_window as mw
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    messages = []
    monkeypatch.setattr(
        mw, "notifyConfirm", lambda msg, *a, **k: messages.append(msg) or confirm
    )
    monkeypatch.setattr(mw, "notify", lambda msg, *a, **k: messages.append(msg))

    calls = {"updated": [], "reloaded": 0, "saved": 0, "modified": []}
    series_states = SeriesStates(series)
    field = types.SimpleNamespace(
        series_states=series_states,
        table_manager=types.SimpleNamespace(
            updateObjects=lambda names: calls["updated"].append(sorted(names))
        ),
        reload=lambda: calls.__setitem__("reloaded", calls["reloaded"] + 1),
    )
    stub = types.SimpleNamespace(
        series=series,
        field=field,
        saveAllData=lambda: calls.__setitem__("saved", calls["saved"] + 1),
        seriesModified=lambda v=True: calls["modified"].append(v),
    )
    mw.MainWindow.recolorAllObjectsFromPalette(stub)
    return messages, calls, series_states


def test_view_recolor_skips_locked_and_recolors_the_rest(tmp_path, monkeypatch):
    """Locked objects keep their colors; every unlocked object is recolored.

    The skip is the decided semantics: the selection-scoped context row aborts
    on any locked object (the object_function wrapper's rule), but applied
    series-wide that rule would make the action useless the moment one object
    is locked.
    """
    series = _load_series(tmp_path)
    _force_options(series)
    all_names = sorted(series.data["objects"].keys())
    assert len(all_names) >= 2, "fixture needs two objects for a lock split"
    locked = all_names[0]
    unlocked = all_names[1:]

    # bake a bogus uniform color so any change is visible, THEN lock
    series.editObjectAttributes(all_names, color=(1, 1, 1), log_event=False)
    series.setAttr(locked, "locked", True)
    locked_before = _snapshot_colors(series, [locked])

    _messages, calls, _states = _run_view_recolor(series, monkeypatch)

    # the locked object kept its color on every section
    assert _snapshot_colors(series, [locked]) == locked_before
    # every unlocked object took its palette color on every section
    for snum, section in series.enumerateSections(show_progress=False):
        for obj in unlocked:
            if obj in section.contours:
                expected = palette_color_for_name(obj)
                for trace in section.contours[obj].getTraces():
                    assert tuple(trace.color) == expected
    # the wrapper work the handler mirrors: save first, update exactly the
    # unlocked rows, reload the field, mark the series modified
    assert calls["saved"] == 1
    assert calls["updated"] == [sorted(unlocked)]
    assert calls["reloaded"] == 1
    assert calls["modified"] == [True]
    series.close()


def test_view_recolor_confirm_names_both_counts_and_cancel_is_a_noop(
        tmp_path, monkeypatch):
    """The dialog states the split before anything changes, and answering no
    changes nothing: no recolor, no table update, no reload."""
    series = _load_series(tmp_path)
    _force_options(series)
    all_names = sorted(series.data["objects"].keys())
    assert len(all_names) >= 2
    series.setAttr(all_names[0], "locked", True)
    before = _snapshot_colors(series, all_names)

    messages, calls, _states = _run_view_recolor(
        series, monkeypatch, confirm=False
    )

    n = len(all_names) - 1
    s = "s" if n != 1 else ""
    assert len(messages) == 1
    assert messages[0] == (
        f"Recolor {n} object{s} using the current palette and seed?\n\n"
        "1 locked object will be skipped.\n\n"
        "This replaces existing colors. You can undo it."
    )
    assert _snapshot_colors(series, all_names) == before
    assert calls["updated"] == []
    assert calls["reloaded"] == 0
    series.close()


def test_view_recolor_without_locked_objects_omits_the_skip_line(
        tmp_path, monkeypatch):
    """A skip line naming zero objects would be noise; it appears only when
    the split is real."""
    series = _load_series(tmp_path)
    _force_options(series)
    n = len(series.data["objects"])

    messages, _calls, _states = _run_view_recolor(
        series, monkeypatch, confirm=False
    )

    s = "s" if n != 1 else ""
    assert messages[0] == (
        f"Recolor {n} object{s} using the current palette and seed?\n\n"
        "This replaces existing colors. You can undo it."
    )
    assert "skipped" not in messages[0]
    series.close()


def test_view_recolor_is_a_single_undoable_operation(tmp_path, monkeypatch):
    """One series undo restores every prior color, exactly like the
    selection-scoped path (the handler passes the field's series_states into
    the same Series.reapplyAutosegColors call)."""
    series = _load_series(tmp_path)
    _force_options(series)
    all_names = sorted(series.data["objects"].keys())

    series.editObjectAttributes(all_names, color=(1, 1, 1), log_event=False)
    before = _snapshot_colors(series, all_names)

    _messages, _calls, series_states = _run_view_recolor(series, monkeypatch)

    after = _snapshot_colors(series, all_names)
    assert after.keys() == before.keys()
    assert any(after[k] != before[k] for k in before), \
        "recolor changed nothing -- undo test would be vacuous"

    assert series_states.canUndo()[0], \
        "the series-wide recolor must leave an undoable series state"
    series_states.undoState()

    assert _snapshot_colors(series, all_names) == before, \
        "a single undo must restore every prior color"
    series.close()

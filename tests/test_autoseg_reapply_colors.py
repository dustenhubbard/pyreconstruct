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
  restores every prior color across every section.
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
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
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

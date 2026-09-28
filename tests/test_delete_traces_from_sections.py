"""Tests for "Delete from sections..." (fork issue #422), the twin of "Copy to
sections...".

Covers:

  * Series.deleteTracesFromSections removes every trace of the given name(s)
    from the chosen sections only; every other section keeps its traces.
  * Chosen sections that hold none of the names are reported back, not
    silently accepted.
  * Sections not chosen are never loaded or saved (the cheap-range property
    copyTracesToSections has).
  * The action rides in trace_actions with Copy, owns a collision-free default
    key, and the trace-list menu variant leaves that key unbound.
  * The shared picker dialog takes the delete title and prompt.
"""
import os
import shutil
import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


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


def _section_without(series, name):
    """A section number holding no trace of `name`. shapes1 has star on every
    section, so one is cleared with the method under test when needed."""
    holding = series.getObjectSections([name])
    empty = sorted(set(series.sections.keys()) - holding)
    if empty:
        return empty[0]
    victim = sorted(holding)[-1]
    series.deleteTracesFromSections([name], {victim})
    series.data.refresh()
    assert name not in series.loadSection(victim).contours
    return victim


def _count(series, snum, name):
    section = series.loadSection(snum)
    if name not in section.contours:
        return 0
    return len(section.contours[name].getTraces())


# ---------------------------------------------------------------------------
# data-model delete
# ---------------------------------------------------------------------------

def test_deletes_only_from_chosen_sections(tmp_path):
    series = _load_series(tmp_path)
    holding = sorted(series.getObjectSections(["star"]))
    assert len(holding) >= 3, "fixture premise: star spans several sections"

    chosen = set(holding[:2])
    keep = holding[2:]
    before_keep = {s: _count(series, s, "star") for s in keep}

    deleted_from, untouched = series.deleteTracesFromSections(["star"], chosen)

    assert deleted_from == sorted(chosen)
    assert untouched == []
    for s in chosen:
        assert _count(series, s, "star") == 0
        assert "star" not in series.loadSection(s).contours
    for s in keep:
        assert _count(series, s, "star") == before_keep[s]


def test_reports_chosen_sections_that_held_nothing(tmp_path):
    series = _load_series(tmp_path)
    empty = _section_without(series, "star")
    target = sorted(series.getObjectSections(["star"]))[0]
    assert target != empty

    deleted_from, untouched = series.deleteTracesFromSections(
        ["star"], {target, empty}
    )

    assert deleted_from == [target]
    assert untouched == [empty]


def test_multiple_names_in_one_pass(tmp_path):
    series = _load_series(tmp_path)
    names = [n for n in series.data["objects"] if n != "star"][:1] + ["star"]
    assert len(names) == 2, "fixture premise: at least two objects"
    snum = sorted(series.getObjectSections(names))[0]
    before_other = {
        (n, s): _count(series, s, n)
        for n in names for s in series.sections if s != snum
    }

    deleted_from, _ = series.deleteTracesFromSections(names, {snum})

    assert deleted_from == [snum]
    for n in names:
        assert _count(series, snum, n) == 0
    for (n, s), c in before_other.items():
        assert _count(series, s, n) == c


def test_untouched_sections_are_not_loaded(tmp_path, monkeypatch):
    """Only the chosen sections that hold the name are visited. A wide range
    over a large series must not load every section in it."""
    series = _load_series(tmp_path)
    holding = sorted(series.getObjectSections(["star"]))
    target = holding[0]
    everything = set(series.sections.keys())

    from PyReconstruct.modules.datatypes import series as series_mod
    seen = []
    real = series_mod.Series.loadSection

    def spy(self, snum, *a, **k):
        seen.append(snum)
        return real(self, snum, *a, **k)

    monkeypatch.setattr(series_mod.Series, "loadSection", spy)
    series.deleteTracesFromSections(["star"], everything - set(holding[1:]))

    assert set(seen) <= {target}, f"loaded sections it had no reason to: {seen}"


def test_nothing_to_delete_leaves_series_unmodified(tmp_path):
    series = _load_series(tmp_path)
    empty = _section_without(series, "star")
    series.modified = False

    deleted_from, untouched = series.deleteTracesFromSections(["star"], {empty})

    assert deleted_from == []
    assert untouched == [empty]
    assert series.modified is False


# ---------------------------------------------------------------------------
# the result message
# ---------------------------------------------------------------------------

def test_format_delete_result_names_real_sections():
    from PyReconstruct.modules.gui.dialog.copy_to_sections import format_delete_result

    msg = format_delete_result([2, 3, 4, 9], [])
    assert msg.startswith("Deleted trace(s) from sections ")
    assert "2-4" in msg and "9" in msg


def test_format_delete_result_lists_untouched():
    from PyReconstruct.modules.gui.dialog.copy_to_sections import format_delete_result

    msg = format_delete_result([5], [6, 7, 8, 12])
    assert "section 5." in msg
    assert "No trace(s) with the selected name(s) on sections 6-8, 12." in msg


def test_format_delete_result_empty():
    from PyReconstruct.modules.gui.dialog.copy_to_sections import format_delete_result

    assert format_delete_result([], []) == ""


# ---------------------------------------------------------------------------
# wiring: gating, shortcut, menus, dialog
# ---------------------------------------------------------------------------

def test_delete_from_sections_greys_out_with_copy(qapp, real_series):
    """Rides in trace_actions with copy_act, the same gate Copy to sections
    uses (tests/test_copy_to_sections_review.py explains why membership IS
    the behavior)."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    from test_copy_to_sections_review import _main_window_stub

    stub = _main_window_stub(real_series)
    MainWindow.createContextMenus(stub)

    assert stub.deletefromsections_act in stub.trace_actions


def test_default_shortcut_is_set_and_unique():
    from PyReconstruct.modules.datatypes.default_settings import (
        default_settings as qsettings_defaults,
    )

    key = qsettings_defaults["deletefromsections_act"]
    assert key == "Ctrl+Alt+X"
    others = {
        n: v for n, v in qsettings_defaults.items()
        if n.endswith("_act") and isinstance(v, str) and v and n != "deletefromsections_act"
    }
    clash = [n for n, v in others.items() if v.strip().lower() == key.lower()]
    assert not clash, f"Ctrl+Alt+X already belongs to {clash}"


def test_shortcut_is_not_cmd_option_d():
    """Ctrl maps to Cmd on macOS and Cmd+Option+D toggles the Dock. Pinned so
    the obvious twin of Ctrl+Alt+C is not picked later by accident."""
    from PyReconstruct.modules.datatypes.default_settings import (
        default_settings as qsettings_defaults,
    )

    assert qsettings_defaults["deletefromsections_act"].lower() != "ctrl+alt+d"


def test_shortcuts_dialog_has_a_row():
    from PyReconstruct.modules.gui.dialog import shortcuts

    names = [r[0] for r in shortcuts.SHORTCUTS if isinstance(r, tuple)] \
        if hasattr(shortcuts, "SHORTCUTS") else None
    if names is None:
        import inspect
        src = inspect.getsource(shortcuts)
        assert '("deletefromsections_act",' in src
    else:
        assert "deletefromsections_act" in names


def test_field_menu_binds_key_and_list_menu_does_not(qapp, real_series):
    from PyReconstruct.modules.gui.main.context_menu_list import (
        get_context_menu_list_trace,
    )
    from test_context_menu_frequency import _Anything, _series

    rows = get_context_menu_list_trace(
        _Anything(series=_series()), is_in_field=False, list_ops=[],
    )
    kbds = {r[0]: r[2] for r in rows if isinstance(r, tuple)}
    assert kbds["deletefromsections_act"] == ""
    labels = {r[0]: r[1] for r in rows if isinstance(r, tuple)}
    assert labels["deletefromsections_act"] == "Delete from sections..."
    # sits right under Copy to sections... in the list menu
    order = [r[0] for r in rows if isinstance(r, tuple)]
    assert order.index("deletefromsections_act") == order.index("copytosections_act") + 1


def test_dialog_takes_delete_title_and_prompt(qapp):
    from test_copy_to_sections_review import _SeriesStub
    from PyReconstruct.modules.gui.dialog.copy_to_sections import CopyToSectionsDialog
    from PySide6.QtWidgets import QLabel

    dlg = CopyToSectionsDialog(
        None, _SeriesStub([1, 2, 3]),
        title="Delete from sections",
        prompt="Delete the selected trace name(s) from the chosen sections.",
    )
    assert dlg.windowTitle() == "Delete from sections"
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert any(t.startswith("Delete the selected trace name(s)") for t in texts)

    default = CopyToSectionsDialog(None, _SeriesStub([1, 2, 3]))
    assert default.windowTitle() == "Copy to sections"

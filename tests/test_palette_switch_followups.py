"""Palette changes that leave the button number or the saved state behind.

Four paths, each found after the palette index clamp for #530:

* `Edit all palettes...` could make a palette of a different length current,
  by switching to its tab or by removing the current one. The mouse palette
  kept the old button number and the old buttons, so a shorter palette raised
  `IndexError` in `updateLabel` and a longer one ran past the old buttons in
  `modifyPaletteButton`.
* A palette CSV with only a header row imported as an empty palette, and
  `MousePalette.reset()` raised on it.
* `Series.importPalettes` saved before the index was checked, and
  `refreshPaletteAfterImport` let a negative button number through.
* The CSV import never marked the series modified, so closing without saving
  dropped the new palette.
"""
import pytest

from PySide6.QtWidgets import QMessageBox

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickTabDialog

pytestmark = pytest.mark.gui


def _add_palette(series, name, rows):
    """Give the series a palette `name` holding the first `rows` buttons."""
    first = next(iter(series.palette_traces))
    series.palette_traces[name] = [
        t.copy() for t in series.palette_traces[first][:rows]
    ]


@pytest.fixture
def run_palette_dialog(monkeypatch):
    """Run `Edit all palettes...` with `action(dialog)` in place of the user.

    The inherited modal `exec` has nobody to dismiss it offscreen, so it is
    replaced by the action and a press of `OK`. Everything the dialog does
    with the result is real.
    """
    def install(action):
        def exec_(self):
            action(self)
            self.accept()
            return self.responses, True
        monkeypatch.setattr(QuickTabDialog, "exec", exec_)
    return install


def _select_tab(dialog, name):
    tabs = dialog.tab_widget
    for index in range(tabs.count()):
        if tabs.tabText(index) == name:
            tabs.setCurrentIndex(index)
            return index
    raise AssertionError(f"no tab named {name}")


def _assert_palette_shows(mw, name, button):
    s = mw.series
    mp = mw.mouse_palette
    assert s.palette_index == [name, button]
    assert len(mp.palette_buttons) == len(s.palette_traces[name])
    assert [b.trace.name for b in mp.palette_buttons] == [
        t.name for t in s.palette_traces[name]
    ]
    assert [b.isChecked() for b in mp.palette_buttons].index(True) == button
    assert mw.field.tracing_trace.name == s.palette_traces[name][button].name


# ---------------------------------------------------------------------------
# Edit all palettes...
# ---------------------------------------------------------------------------

def test_switching_to_a_shorter_palette_selects_its_first_button(
    main_window, run_palette_dialog
):
    mw = main_window
    _add_palette(mw.series, "short", 5)
    mw.mouse_palette.activatePaletteButton(13)

    run_palette_dialog(lambda d: _select_tab(d, "short"))
    mw.mouse_palette.modifyAllPaletteButtons()

    _assert_palette_shows(mw, "short", 0)


def test_removing_the_current_palette_selects_a_button_that_exists(
    main_window, run_palette_dialog, monkeypatch
):
    mw = main_window
    first = mw.series.palette_index[0]
    _add_palette(mw.series, "short", 5)
    mw.mouse_palette.activatePaletteButton(13)
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok)
    )

    def remove_current(dialog):
        dialog.removePalette(_select_tab(dialog, first))
    run_palette_dialog(remove_current)
    mw.mouse_palette.modifyAllPaletteButtons()

    assert first not in mw.series.palette_traces
    _assert_palette_shows(mw, "short", 0)


def test_switching_to_a_longer_palette_shows_all_its_buttons(
    main_window, run_palette_dialog
):
    mw = main_window
    first = mw.series.palette_index[0]
    _add_palette(mw.series, "short", 5)
    mw.series.palette_index[:] = ["short", 3]
    mw.mouse_palette.reset()

    run_palette_dialog(lambda d: _select_tab(d, first))
    mw.mouse_palette.modifyAllPaletteButtons()

    _assert_palette_shows(mw, first, 3)


def test_editing_the_same_palette_keeps_the_button(
    main_window, run_palette_dialog
):
    mw = main_window
    first = mw.series.palette_index[0]
    mw.mouse_palette.activatePaletteButton(13)
    buttons = list(mw.mouse_palette.palette_buttons)

    run_palette_dialog(lambda d: None)
    mw.mouse_palette.modifyAllPaletteButtons()

    _assert_palette_shows(mw, first, 13)
    # the same length, so the buttons are updated rather than rebuilt
    assert mw.mouse_palette.palette_buttons == buttons


# ---------------------------------------------------------------------------
# Import from CSV...
# ---------------------------------------------------------------------------

def _palette_csv(series, tmp_path, rows):
    """A palette CSV with `rows` rows, written by the series' own exporter."""
    full = tmp_path / "full.csv"
    series.exportTracePaletteCSV(str(full))
    lines = full.read_text().splitlines()
    out = tmp_path / f"rows{rows}.csv"
    out.write_text("\n".join(lines[: rows + 1]) + "\n")
    return out


@pytest.mark.parametrize("extra", ["", "\n", " \n\n"])
def test_a_csv_with_no_rows_is_refused(
    main_window, main_window_dialogs, tmp_path, extra
):
    mw = main_window
    s = mw.series
    mw.mouse_palette.activatePaletteButton(13)
    before = {name: len(traces) for name, traces in s.palette_traces.items()}
    csv = _palette_csv(s, tmp_path, 0)
    csv.write_text(csv.read_text() + extra)
    mw.seriesModified(False)

    main_window_dialogs.file_responses = [str(csv)]
    mw.importTracePaletteCSV()

    assert {n: len(t) for n, t in s.palette_traces.items()} == before
    assert s.palette_index[1] == 13
    assert main_window_dialogs.notices == [
        "This CSV file has no palette rows. Nothing was imported."
    ]
    assert not s.modified


def test_a_csv_import_marks_the_series_modified(
    main_window, main_window_dialogs, tmp_path
):
    mw = main_window
    s = mw.series
    mw.seriesModified(False)

    main_window_dialogs.file_responses = [str(_palette_csv(s, tmp_path, 5))]
    mw.importTracePaletteCSV()

    assert s.modified
    assert mw.windowTitle().endswith("*")


def test_series_importer_skips_blank_lines(real_series, tmp_path):
    csv = _palette_csv(real_series, tmp_path, 2)
    csv.write_text(csv.read_text() + "\n  \n")

    assert real_series.importTracePaletteCSV(str(csv), "two")
    assert len(real_series.palette_traces["two"]) == 2


# ---------------------------------------------------------------------------
# Import from another series
# ---------------------------------------------------------------------------

def test_import_palettes_checks_the_index_before_it_saves(
    real_series, monkeypatch
):
    s = real_series
    g = s.palette_index[0]
    s.palette_index[1] = 13
    class Other:  # importPalettes reads only palette_traces
        palette_traces = {"five": [t.copy() for t in s.palette_traces[g][:5]]}

    saved = []
    monkeypatch.setattr(
        Series, "save", lambda self: saved.append(list(self.palette_index))
    )
    s.importPalettes(Other(), [("five", g)], log_event=False)

    assert saved == [[g, 0]]
    assert s.palette_index == [g, 0]


def test_refresh_after_import_fixes_a_negative_index(main_window):
    mw = main_window
    g = mw.series.palette_index[0]
    mw.series.palette_index[1] = -1

    mw.refreshPaletteAfterImport({g})

    _assert_palette_shows(mw, g, 0)


# ---------------------------------------------------------------------------
# The mode buttons after a rebuild
# ---------------------------------------------------------------------------

def _checked_mode(mp):
    checked = [m for b, m, _ in mp.mode_buttons.values() if b.isChecked()]
    assert len(checked) == 1
    return checked[0]


@pytest.mark.parametrize("tool", ["Closed Trace", "Stamp"])
def test_switching_palette_length_keeps_the_tool(
    main_window, run_palette_dialog, tool
):
    mw = main_window
    _add_palette(mw.series, "short", 5)
    mw.mouse_palette.activateModeButton(tool)
    mode = mw.mouse_palette.mode_buttons[tool][1]

    run_palette_dialog(lambda d: _select_tab(d, "short"))
    mw.mouse_palette.modifyAllPaletteButtons()

    assert mw.field.mouse_mode == mode
    assert _checked_mode(mw.mouse_palette) == mode


def test_csv_import_keeps_the_tool(main_window, main_window_dialogs, tmp_path):
    mw = main_window
    mw.mouse_palette.activateModeButton("Stamp")
    mode = mw.mouse_palette.mode_buttons["Stamp"][1]

    main_window_dialogs.file_responses = [
        str(_palette_csv(mw.series, tmp_path, 5))
    ]
    mw.importTracePaletteCSV()

    assert mw.field.mouse_mode == mode
    assert _checked_mode(mw.mouse_palette) == mode

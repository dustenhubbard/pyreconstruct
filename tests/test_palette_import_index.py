"""A palette index past the end of its palette (fork #530).

Importing a palette CSV kept the selected button number. With button 14
selected and a five-row CSV imported, `MousePalette.reset()` raised
`IndexError`, the index was left at 13 of a five-button palette, and a save
wrote it to the `.jser`. Opening that file then raised the same `IndexError`
in `_buildFieldAndPalette`, so one import made the series unopenable.

Both ends are covered: the import leaves a valid index, and a series saved
with a bad index opens with it clamped.
"""
import shutil

from PyReconstruct.modules.datatypes import Series


def _short_palette_csv(series, tmp_path, rows=5):
    """A palette CSV with `rows` rows, written by the series' own exporter."""
    full = tmp_path / "full.csv"
    series.exportTracePaletteCSV(str(full))
    lines = full.read_text().splitlines()
    assert len(lines) > rows + 1, "the fixture palette must be longer than the CSV"
    short = tmp_path / "short5.csv"
    short.write_text("\n".join(lines[: rows + 1]) + "\n")
    return short


# ---------------------------------------------------------------------------
# the import
# ---------------------------------------------------------------------------

def test_importing_a_shorter_palette_selects_its_first_button(
    main_window, main_window_dialogs, tmp_path
):
    mw = main_window
    s = mw.series
    mw.mouse_palette.activatePaletteButton(13)
    assert s.palette_index[1] == 13

    main_window_dialogs.file_responses = [str(_short_palette_csv(s, tmp_path))]
    mw.importTracePaletteCSV()

    assert s.palette_index == ["short5", 0]
    assert len(s.palette_traces["short5"]) == 5
    assert len(mw.mouse_palette.palette_buttons) == 5
    assert mw.mouse_palette.palette_buttons[0].isChecked()
    assert mw.field.tracing_trace.name == s.palette_traces["short5"][0].name


def test_importing_keeps_a_button_number_the_new_palette_has(
    main_window, main_window_dialogs, tmp_path
):
    mw = main_window
    s = mw.series
    mw.mouse_palette.activatePaletteButton(3)

    main_window_dialogs.file_responses = [str(_short_palette_csv(s, tmp_path))]
    mw.importTracePaletteCSV()

    assert s.palette_index == ["short5", 3]
    assert mw.mouse_palette.palette_buttons[3].isChecked()


def test_a_series_saved_after_the_import_opens_again(
    main_window, main_window_dialogs, tmp_path
):
    mw = main_window
    s = mw.series
    mw.mouse_palette.activatePaletteButton(13)
    main_window_dialogs.file_responses = [str(_short_palette_csv(s, tmp_path))]
    mw.importTracePaletteCSV()

    s.modified = True
    main_window_dialogs.save_response = "yes"
    mw.saveToJser()
    copy = tmp_path / "reopen" / "copy.jser"
    copy.parent.mkdir()
    shutil.copy(s.jser_fp, copy)

    mw.openSeries(jser_fp=str(copy), query_prev=False)

    assert mw.series.jser_fp == str(copy)
    assert mw.series.palette_index == ["short5", 0]


# ---------------------------------------------------------------------------
# opening a file that already has a bad index
# ---------------------------------------------------------------------------

def _save_with_index(series, index):
    """Write `index` into the series' `.jser` and return the path, closed."""
    fp = series.jser_fp
    series.palette_index = list(index)
    series.saveJser()
    series.close()
    return fp


def test_an_index_past_the_end_opens_at_the_first_button(real_series):
    g = real_series.palette_index[0]
    n = len(real_series.palette_traces[g])
    fp = _save_with_index(real_series, [g, n + 8])

    reopened = Series.openJser(fp)
    try:
        assert reopened.palette_index == [g, 0]
    finally:
        reopened.close()


def test_a_negative_index_opens_at_the_first_button(real_series):
    g = real_series.palette_index[0]
    fp = _save_with_index(real_series, [g, -1])

    reopened = Series.openJser(fp)
    try:
        assert reopened.palette_index == [g, 0]
    finally:
        reopened.close()


def test_an_unknown_palette_name_opens_on_the_first_palette(real_series):
    first = next(iter(real_series.palette_traces))
    fp = _save_with_index(real_series, ["no such palette", 2])

    reopened = Series.openJser(fp)
    try:
        assert reopened.palette_index == [first, 2]
    finally:
        reopened.close()


def test_a_valid_index_opens_unchanged(real_series):
    g = real_series.palette_index[0]
    fp = _save_with_index(real_series, [g, 4])

    reopened = Series.openJser(fp)
    try:
        assert reopened.palette_index == [g, 4]
    finally:
        reopened.close()


def test_a_bad_index_file_opens_in_the_window(
    main_window, main_window_dialogs, tmp_path
):
    s = main_window.series
    g = s.palette_index[0]
    # copy the fixture and break its index, the way a save after the
    # unfixed import did
    broken = tmp_path / "broken" / "broken.jser"
    broken.parent.mkdir()
    shutil.copy(s.jser_fp, broken)
    _save_with_index(Series.openJser(str(broken)), [g, 99])

    main_window.openSeries(jser_fp=str(broken), query_prev=False)

    assert main_window.series.jser_fp == str(broken)
    assert main_window.series.palette_index == [g, 0]
    assert main_window.mouse_palette.palette_buttons[0].isChecked()

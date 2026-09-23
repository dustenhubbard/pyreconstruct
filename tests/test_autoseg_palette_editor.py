"""Tests for the autoseg import-colors editor (Series > Options > View).

The editor backs the ``autoseg_color_palette`` / ``autoseg_color_seed`` options.
These tests exercise its save path (accept -> set), reset-to-default, the
minimum-color floor, that what it persists is exactly what the import preview
and shuffle consume, and the live embedded picker that replaced the modal
dialog in September 2026 -- all offscreen, no real dialogs.
"""

import pytest

from PyReconstruct.modules.backend.autoseg.palette import (
    DEFAULT_AUTOSEG_PALETTE,
    palette_color,
)
from PyReconstruct.modules.gui.dialog import autoseg_palette as ape
from PyReconstruct.modules.gui.dialog.autoseg_palette import (
    AutosegColorsWidget,
    MIN_PALETTE_COLORS,
    normalize_palette,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


class _SeriesStub:
    """Minimal series exposing just the option get/set the editor uses."""

    def __init__(self, palette=None, seed=0):
        self.store = {
            "autoseg_color_palette": [] if palette is None else palette,
            "autoseg_color_seed": seed,
        }
        self.writes = []

    def getOption(self, name, use_defaults=False):
        if use_defaults:
            return {"autoseg_color_palette": [], "autoseg_color_seed": 0}[name]
        return self.store[name]

    def setOption(self, name, value):
        self.store[name] = value
        self.writes.append((name, value))


def _widget(qapp, series, use_defaults=False):
    return AutosegColorsWidget(None, series, use_defaults)


# --- normalize_palette (pure) ----------------------------------------------


def test_normalize_default_returns_empty():
    # an unchanged default palette persists as [] so it keeps tracking the
    # shipped default instead of freezing today's colors
    assert normalize_palette([list(c) for c in DEFAULT_AUTOSEG_PALETTE]) == []
    assert normalize_palette([tuple(c) for c in DEFAULT_AUTOSEG_PALETTE]) == []


def test_normalize_custom_returns_list_of_lists():
    custom = [(1, 2, 3), (4, 5, 6)]
    assert normalize_palette(custom) == [[1, 2, 3], [4, 5, 6]]


def test_normalize_near_default_still_persists_explicitly():
    near = [list(c) for c in DEFAULT_AUTOSEG_PALETTE]
    near[0] = [0, 0, 0]  # one channel changed -> no longer the default
    out = normalize_palette(near)
    assert out != []
    assert out[0] == [0, 0, 0]


# --- construction: what the editor shows -----------------------------------


def test_empty_option_shows_default_palette(qapp):
    w = _widget(qapp, _SeriesStub(palette=[]))
    assert w.colors == [list(c) for c in DEFAULT_AUTOSEG_PALETTE]
    assert w.list.count() == len(DEFAULT_AUTOSEG_PALETTE)


def test_stored_custom_palette_is_shown(qapp):
    custom = [[10, 20, 30], [40, 50, 60], [70, 80, 90]]
    w = _widget(qapp, _SeriesStub(palette=custom, seed=7))
    assert w.colors == custom
    assert w.list.count() == 3
    assert w.seed_edit.text() == "7"


# --- save path (accept -> set) ---------------------------------------------


def test_set_round_trips_custom_palette_and_seed(qapp):
    series = _SeriesStub(palette=[], seed=0)
    w = _widget(qapp, series)
    w.colors = [[10, 20, 30], [40, 50, 60]]
    w.seed_edit.setText("12345")
    assert w.accept(close=False) is True
    w.set()
    assert series.store["autoseg_color_palette"] == [[10, 20, 30], [40, 50, 60]]
    assert series.store["autoseg_color_seed"] == 12345


def test_set_normalizes_unchanged_default_to_empty(qapp):
    # opening on the default palette and saving without edits keeps the option []
    series = _SeriesStub(palette=[], seed=3)
    w = _widget(qapp, series)
    assert w.accept(close=False) is True
    w.set()
    assert series.store["autoseg_color_palette"] == []
    assert series.store["autoseg_color_seed"] == 3


def test_saved_palette_is_consumable_by_preview_and_import(qapp):
    """What the editor writes must be exactly what palette_color reads -- the
    same option the live preview, shuffle and import all consume."""
    series = _SeriesStub(palette=[], seed=0)
    w = _widget(qapp, series)
    custom = [[10, 20, 30], [40, 50, 60], [200, 100, 0]]
    w.colors = [list(c) for c in custom]
    assert w.accept(close=False) is True
    w.set()
    saved = series.store["autoseg_color_palette"]
    seen = {palette_color(i, saved, series.store["autoseg_color_seed"])
            for i in range(1, 500)}
    assert seen  # non-empty
    assert all(list(c) in custom for c in seen)


# --- reset to default -------------------------------------------------------


def test_reset_to_default_restores_cvd_palette(qapp):
    series = _SeriesStub(palette=[[1, 1, 1], [2, 2, 2]], seed=0)
    w = _widget(qapp, series)
    assert w.colors == [[1, 1, 1], [2, 2, 2]]
    w._reset_default()
    assert w.colors == [list(c) for c in DEFAULT_AUTOSEG_PALETTE]
    w.set()
    # reset + save collapses back to the "use built-in default" sentinel
    assert series.store["autoseg_color_palette"] == []


# --- minimum-color floor ----------------------------------------------------


def test_remove_refuses_below_minimum(qapp, monkeypatch):
    notes = []
    monkeypatch.setattr(ape, "notify", lambda msg: notes.append(msg))
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(0)
    w._remove_selected()
    assert len(w.colors) == MIN_PALETTE_COLORS  # unchanged
    assert notes  # user was told why


def test_remove_button_disabled_at_minimum(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(0)
    assert not w.remove_btn.isEnabled()


def test_remove_allowed_above_minimum(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6], [7, 8, 9]]))
    w.list.setCurrentRow(1)
    assert w.remove_btn.isEnabled()
    w._remove_selected()
    assert w.colors == [[1, 2, 3], [7, 8, 9]]


def test_accept_rejects_below_minimum(qapp, monkeypatch):
    notes = []
    monkeypatch.setattr(ape, "notify", lambda msg: notes.append(msg))
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.colors = [[1, 2, 3]]  # forced below floor
    assert w.accept(close=False) is False
    assert notes


# --- seed validation --------------------------------------------------------


def test_accept_treats_empty_seed_as_zero(qapp):
    w = _widget(qapp, _SeriesStub(palette=[], seed=9))
    w.seed_edit.setText("")
    assert w.accept(close=False) is True
    assert w._seed == 0


def test_accept_rejects_non_integer_seed(qapp, monkeypatch):
    notes = []
    monkeypatch.setattr(ape, "notify", lambda msg: notes.append(msg))
    w = _widget(qapp, _SeriesStub(palette=[], seed=0))
    w.seed_edit.setText("not-a-number")
    assert w.accept(close=False) is False
    assert notes


# --- add / edit via the color dialog (stubbed) ------------------------------


# --- the live picker: one, embedded, bound to the selected swatch -----------
#
# The old page opened a modal QColorDialog per swatch (his bug report,
# 2026-09-14: "picking a color dismisses the color picker window every time").
# The picker is now a child widget of the page; these pin the mechanics the
# design pass called load-bearing.

def _rgb(color):
    return [color.red(), color.green(), color.blue()]


def test_picker_is_embedded_and_qt_owned(qapp):
    from PySide6.QtWidgets import QColorDialog
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    assert w.picker.parent() is w
    assert not w.picker.isWindow(), "the picker must be part of the page, not a window"
    assert w.picker.testOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
    assert w.picker.testOption(QColorDialog.ColorDialogOption.NoButtons)


def test_selecting_a_swatch_binds_the_picker_without_writing(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(1)
    assert _rgb(w.picker.currentColor()) == [4, 5, 6]
    assert w.colors == [[1, 2, 3], [4, 5, 6]]      # binding is not an edit
    assert not w.revert_btn.isEnabled()


def test_a_live_change_recolors_only_the_bound_swatch(qapp):
    from PySide6.QtGui import QColor
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(1)
    w.picker.setCurrentColor(QColor(99, 88, 77))     # what a slider drag emits
    assert w.colors == [[1, 2, 3], [99, 88, 77]]
    assert w.list.count() == 2                         # no rebuild mid-drag
    assert w.list.item(1).text() == "#63584D"
    assert w.revert_btn.isEnabled()


def test_retargeting_does_not_bleed_the_previous_color(qapp):
    from PySide6.QtGui import QColor
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(0)
    w.picker.setCurrentColor(QColor(200, 100, 50))
    w.list.setCurrentRow(1)                            # programmatic setCurrentColor fires too
    assert w.colors == [[200, 100, 50], [4, 5, 6]]
    assert _rgb(w.picker.currentColor()) == [4, 5, 6]


def test_revert_and_escape_put_the_swatch_back(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(1)
    w.picker.setCurrentColor(QColor(99, 88, 77))
    w._revert_current()
    assert w.colors == [[1, 2, 3], [4, 5, 6]]
    w.picker.setCurrentColor(QColor(9, 9, 9))
    QTest.keyClick(w.picker, Qt.Key.Key_Escape)
    assert w.colors == [[1, 2, 3], [4, 5, 6]]
    assert w.picker.isVisibleTo(w), "Esc must not hide the embedded picker"


def test_nothing_reaches_the_series_before_set(qapp):
    from PySide6.QtGui import QColor
    series = _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]])
    w = _widget(qapp, series)
    w.list.setCurrentRow(0)
    w.picker.setCurrentColor(QColor(7, 7, 7))
    assert series.writes == []
    assert w.accept(close=False) is True
    w.set()
    assert series.store["autoseg_color_palette"] == [[7, 7, 7], [4, 5, 6]]


# --- bulk entry, copy, duplicate, undo, preview ----------------------------

def test_add_colors_field_takes_hex_and_rgb_tokens(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.add_edit.setText("#1B9E77 D95F02 27,158,119 junk 300,0,0")
    w._add_from_text()
    assert w.colors[2:] == [[27, 158, 119], [217, 95, 2], [27, 158, 119]]
    assert w.list.currentRow() == 4                    # the last one added is bound
    assert "Added 3" in w.status.text() and "skipped 2" in w.status.text()
    assert w.add_edit.text() == ""


def test_add_with_an_empty_field_copies_the_selected_swatch(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(1)
    w._add_from_text_or_copy()
    assert w.colors == [[1, 2, 3], [4, 5, 6], [4, 5, 6]]


def test_copy_puts_one_hex_per_line_on_the_clipboard(qapp):
    from PySide6.QtWidgets import QApplication
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w._copy_palette()
    assert QApplication.clipboard().text() == "#010203\n#040506"


def test_remove_several_at_once_stops_at_the_floor(qapp, monkeypatch):
    notes = []
    monkeypatch.setattr(ape, "notify", lambda msg: notes.append(msg))
    w = _widget(qapp, _SeriesStub(palette=[[1, 1, 1], [2, 2, 2], [3, 3, 3], [4, 4, 4]]))
    for row in (1, 2, 3):
        w.list.item(row).setSelected(True)
    w.list.item(0).setSelected(False)
    w._remove_selected()
    assert w.colors == [[1, 1, 1], [2, 2, 2], [3, 3, 3], [4, 4, 4]] and notes
    w.list.clearSelection()
    for row in (1, 2):
        w.list.item(row).setSelected(True)
    w._remove_selected()
    assert w.colors == [[1, 1, 1], [4, 4, 4]]


def test_undo_steps_back_through_edits(qapp):
    from PySide6.QtGui import QColor
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]]))
    w.list.setCurrentRow(0)
    w.picker.setCurrentColor(QColor(7, 7, 7))
    w.picker.setCurrentColor(QColor(8, 8, 8))          # same swatch: one undo step
    w._add_colors([[9, 9, 9]])
    w._undo_last()
    assert w.colors == [[8, 8, 8], [4, 5, 6]]
    w._undo_last()
    assert w.colors == [[1, 2, 3], [4, 5, 6]]


def test_preview_strip_is_what_import_will_do(qapp):
    custom = [[10, 0, 0], [0, 10, 0], [0, 0, 10]]
    w = _widget(qapp, _SeriesStub(palette=custom, seed=5))
    assert w._preview_colors() == [palette_color(i, custom, 5) for i in range(1, 17)]
    w.seed_edit.setText("6")
    assert w._preview_colors() == [palette_color(i, custom, 6) for i in range(1, 17)]


def test_status_says_when_a_length_change_reassigns_every_label(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6], [7, 8, 9]]))
    assert "3 colors" in w.status.text() and "length changed" not in w.status.text()
    w._add_colors([[0, 0, 0]])
    assert "Palette length changed 3 to 4" in w.status.text()
    assert "Recolor all objects from palette" in w.status.text()


def test_shuffle_changes_the_seed_field(qapp):
    w = _widget(qapp, _SeriesStub(palette=[[1, 2, 3], [4, 5, 6]], seed=1))
    w._shuffle()
    assert w.seed_edit.text() != "1"
    assert w.accept(close=False) is True


def test_parse_colors_pure():
    from PyReconstruct.modules.gui.dialog.autoseg_palette import parse_colors
    assert parse_colors("#FFffFF; 000000\n1,2,3  nope 256,0,0") == ([[255, 255, 255], [0, 0, 0], [1, 2, 3]], 2)
    assert parse_colors("") == ([], 0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

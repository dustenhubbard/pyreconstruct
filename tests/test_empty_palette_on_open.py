"""A series saved with an empty palette opens and works.

Before the header-only palette CSV import was refused (#583), it saved a palette with
no buttons. A file holding one still crashed: `MousePalette.reset()` and
`updateLabel` index `palette_traces[g][0]` when that palette was current at
open or was picked in `Edit all palettes...`. Loading now drops empty
palettes, and the dialog refuses to save one.
"""
import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickTabDialog

pytestmark = pytest.mark.gui


def _write_empty_palettes(fp, empty_names, current=None, empty_all=False):
    """Rewrite the jser at `fp` the way the old import left it: palettes
    `empty_names` with no buttons, and `current` as the current palette."""
    s = Series.openJser(str(fp))
    try:
        if empty_all:
            for name in s.palette_traces:
                s.palette_traces[name] = []
        for name in empty_names:
            s.palette_traces[name] = []
        if current is not None:
            s.palette_index = [current, 0]
        s.save()
        s.saveJser()
    finally:
        s.close()


@pytest.fixture
def empty_current_jser(series_jser):
    """The fixture series with an empty palette `empty` that is current."""
    _write_empty_palettes(series_jser, ["empty"], current="empty")
    return series_jser


def test_an_empty_palette_is_dropped_on_open(series_jser):
    s = Series.openJser(str(series_jser))
    first = next(iter(s.palette_traces))
    s.close()
    _write_empty_palettes(series_jser, ["empty"])

    s = Series.openJser(str(series_jser))
    try:
        assert "empty" not in s.palette_traces
        assert s.palette_index[0] == first
        assert all(s.palette_traces.values())
    finally:
        s.close()


def test_an_empty_current_palette_falls_back_to_one_that_exists(
    empty_current_jser,
):
    s = Series.openJser(str(empty_current_jser))
    try:
        assert "empty" not in s.palette_traces
        g, i = s.palette_index
        assert g in s.palette_traces
        assert i == 0
    finally:
        s.close()


def test_a_series_with_only_empty_palettes_gets_the_default(series_jser):
    _write_empty_palettes(series_jser, [], empty_all=True)

    s = Series.openJser(str(series_jser))
    try:
        assert list(s.palette_traces) == ["palette1"]
        assert [t.name for t in s.palette_traces["palette1"]] == [
            t.name for t in Series.getDefaultPaletteTraces()
        ]
        assert s.palette_index == ["palette1", 0]
    finally:
        s.close()


def test_the_window_opens_on_an_empty_current_palette(
    empty_current_jser, main_window
):
    mw = main_window
    g, i = mw.series.palette_index
    palette = mw.series.palette_traces[g]
    assert palette
    assert len(mw.mouse_palette.palette_buttons) == len(palette)
    assert mw.field.tracing_trace.name == palette[i].name


@pytest.fixture
def run_palette_dialog(monkeypatch):
    """Run `Edit all palettes...` with `action(dialog)` in place of the user,
    then press `OK`."""
    def install(action):
        def exec_(self):
            action(self)
            self.accept()
            return self.responses, True
        monkeypatch.setattr(QuickTabDialog, "exec", exec_)
    return install


def test_the_dialog_refuses_to_save_an_empty_palette(
    main_window, run_palette_dialog, monkeypatch
):
    from PyReconstruct.modules.gui.dialog import trace_palette

    notices = []
    monkeypatch.setattr(trace_palette, "notify", notices.append)
    mw = main_window
    s = mw.series
    # a palette with no buttons, as a series could hold before it was reopened
    s.palette_traces["empty"] = []
    before = {name: [t.name for t in p] for name, p in s.palette_traces.items()}
    index_before = list(s.palette_index)

    def pick_empty(dialog):
        tabs = dialog.tab_widget
        for index in range(tabs.count()):
            if tabs.tabText(index) == "empty":
                tabs.setCurrentIndex(index)

    run_palette_dialog(pick_empty)
    mw.mouse_palette.modifyAllPaletteButtons()

    assert notices == [
        "The palette empty has no buttons. Nothing was changed."
    ]
    assert {name: [t.name for t in p] for name, p in s.palette_traces.items()} == before
    assert s.palette_index == index_before
    assert len(mw.mouse_palette.palette_buttons) == len(
        s.palette_traces[index_before[0]]
    )

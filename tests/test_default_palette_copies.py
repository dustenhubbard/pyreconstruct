"""Each button of the default palette has its own trace.

`Series.getDefaultPaletteTraces` built the ten default shapes once and
returned `palette_traces * 2`, so buttons 0-9 and 10-19 held the same Trace
objects. A button edit changes its trace in place, so editing button 3 also
changed button 13, and the save wrote both. `Reset current palette` and a
series opened with no palette both use this list.
"""
import pytest

from PyReconstruct.modules.constants import traces as trace_constants
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.palette import buttons


def _row(trace):
    return trace.getList(include_name=True)


def test_every_default_button_is_its_own_trace():
    traces = Series.getDefaultPaletteTraces()
    n = len(trace_constants.default_traces)
    assert len(traces) == 2 * n
    assert len({id(t) for t in traces}) == len(traces)
    for i in range(n):
        a, b = traces[i], traces[i + n]
        assert _row(a) == _row(b), "the two rows hold the same shapes"
        assert a.color is not b.color
        assert a.fill_mode is not b.fill_mode
        assert a.points is not b.points


def test_default_traces_share_nothing_with_the_constant():
    const = trace_constants.default_traces
    for t in Series.getDefaultPaletteTraces():
        for row in const:
            assert t.color is not row[3]
            assert t.fill_mode is not row[7]


def test_editing_one_default_button_leaves_its_pair_alone():
    traces = Series.getDefaultPaletteTraces()
    n = len(trace_constants.default_traces)
    pair_before = _row(traces[3 + n])
    const_before = [list(map(str, r)) for r in trace_constants.default_traces]

    # what TraceButton.openDialog does to its trace
    traces[3].name = "edited"
    traces[3].color = (1, 2, 3)
    traces[3].points = [(0, 0), (1, 0), (1, 1)]
    traces[3].fill_mode = ("solid", "always")

    assert _row(traces[3 + n]) == pair_before
    assert [list(map(str, r)) for r in trace_constants.default_traces] == const_before
    assert _row(Series.getDefaultPaletteTraces()[3]) == pair_before


def test_saving_keeps_the_pair_separate(series_jser):
    """A series whose palettes are all empty opens with the default palette.
    Edit one button, save, reopen: its pair is still the default."""
    s = Series.openJser(str(series_jser))
    try:
        for name in s.palette_traces:
            s.palette_traces[name] = []
        s.save()
        s.saveJser()
    finally:
        s.close()

    n = len(trace_constants.default_traces)
    s = Series.openJser(str(series_jser))
    try:
        palette = s.palette_traces["palette1"]
        default_row = _row(palette[3 + n])
        palette[3].name = "edited"
        palette[3].color = (1, 2, 3)
        assert _row(palette[3 + n]) == default_row
        s.save()
        s.saveJser()
    finally:
        s.close()

    s = Series.openJser(str(series_jser))
    try:
        palette = s.palette_traces["palette1"]
        assert palette[3].name == "edited"
        assert tuple(palette[3].color) == (1, 2, 3)
        assert _row(palette[3 + n]) == default_row
    finally:
        s.close()


class _EditedTrace:
    """What TraceDialog returns when the user renames and recolors."""

    name = "edited"
    color = (1, 2, 3)
    points = None
    tags = None
    fill_mode = (None, None)
    obj_defaults = None

    def getRadius(self):
        return None


class _FakeTraceDialog:
    def __init__(self, *args, **kwargs):
        self.tag_choices = None

    def exec(self):
        return _EditedTrace(), True


@pytest.mark.gui
def test_reset_palette_then_edit_one_button(main_window, monkeypatch):
    """`Reset current palette`, then edit button 3 through its dialog."""
    mw = main_window
    mw.resetTracePalette()
    n = len(trace_constants.default_traces)
    pbuttons = mw.mouse_palette.palette_buttons
    assert len(pbuttons) == 2 * n
    pair_before = _row(pbuttons[3 + n].trace)

    monkeypatch.setattr(buttons, "TraceDialog", _FakeTraceDialog)
    pbuttons[3].openDialog()

    g = mw.series.palette_index[0]
    assert pbuttons[3].trace.name == "edited"
    assert mw.series.palette_traces[g][3].name == "edited"
    assert _row(pbuttons[3 + n].trace) == pair_before
    assert _row(mw.series.palette_traces[g][3 + n]) == pair_before

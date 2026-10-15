"""`propagateTo` writes the flickered-away section before it works.

`propagateTo` saved only the current section, then reloaded both sections
from their files at the end. A trace drawn on the B section (the one the user
flickered away from) and not yet written was thrown away by that reload.
"""
import types

import pytest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main import field_widget_4_data as fw

pytestmark = pytest.mark.gui

NAME = "propagate_keep_obj"


@pytest.fixture
def field(main_window, monkeypatch):
    monkeypatch.setattr(
        fw, "getProgbar",
        lambda *a, **k: types.SimpleNamespace(
            setValue=lambda v: None, close=lambda: None
        ),
    )
    field = main_window.field
    # the fixture series ships with its sections locked
    for n in field.series.sections:
        section = field.series.loadSection(n)
        section.align_locked = False
        section.save()
    field.reload()
    return field


def _flicker_setup(field):
    """Leave the field on the first section with the second as B section."""
    snums = sorted(field.series.sections)
    start, other = snums[0], snums[1]
    field.changeSection(start)
    field.changeSection(other)
    field.changeSection(start)
    assert field.b_section is not None and field.b_section.n == other
    return start, other


# --- item: propagateTo writes the B section first --------------------------

@pytest.mark.parametrize("to_end", [True, False])
def test_unsaved_trace_on_b_section_survives_propagation(field, to_end):
    start, other = _flicker_setup(field)

    # draw on the B section and leave it unsaved: flicker to it, draw, and
    # flicker back without a save in between
    field.mainwindow.flickerSections()
    assert field.section.n == other
    wx, wy, ww, wh = field.series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    pts = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(pts, field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    field.mainwindow.flickerSections()
    assert field.section.n == start
    assert field.b_section.n == other
    assert NAME in [t.name for t in field.b_section.tracesAsList()]

    field.setPropagationMode(True)
    field.translateTform(3, 4)
    field.propagateTo(to_end=to_end)

    assert NAME in [t.name for t in field.b_section.tracesAsList()], "gone in memory"
    on_disk = field.series.loadSection(other)
    assert NAME in [t.name for t in on_disk.tracesAsList()], "gone on disk"
    if to_end:
        # the B section is after the current one, so it moved as well
        assert on_disk.tform.equals(field.b_section.tform)

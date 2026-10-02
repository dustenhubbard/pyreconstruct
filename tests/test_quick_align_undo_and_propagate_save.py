"""`quickAlign` records its shift like every other alignment, and
`propagateTo` writes the flickered-away section before it works.

`quickAlign` used to assign `section.tform` directly. The shift was in the
section's undo state, but it skipped what `changeTform` does on top: the
propagation recording, the record of where the section stood before the
latest change, and the "Modify transform" log entry. It has no menu entry
(`menubar.py` keeps it commented out), so the tests call it directly.

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


@pytest.fixture
def fake_registration(monkeypatch):
    from skimage import registration

    # (row shift, column shift), error, phase difference
    monkeypatch.setattr(
        registration, "phase_cross_correlation",
        lambda a, b: ((-8.0, 12.0), 0.0, 0.0),
    )


# --- item: quickAlign goes through changeTform -----------------------------

def test_quick_align_is_undone_and_redone(field, fake_registration):
    _flicker_setup(field)
    before = field.section.tform.copy()

    field.quickAlign()
    aligned = field.section.tform.copy()
    assert not aligned.equals(before), "the alignment should move the section"

    field.undoState()
    assert field.section.tform.equals(before)
    field.undoState(redo=True)
    assert field.section.tform.equals(aligned)


def test_quick_align_is_recorded_for_propagation(field, fake_registration):
    start, other = _flicker_setup(field)
    later = [n for n in sorted(field.series.sections) if n > start]
    before_later = {n: field.series.loadSection(n).tform.copy() for n in later}
    before = field.section.tform.copy()

    field.setPropagationMode(True)
    field.quickAlign()
    delta = field.section.tform * before.inverted()
    assert field.stored_tform.equals(delta)

    field.propagateTo(to_end=True)
    for n in later:
        got = field.series.loadSection(n).tform
        assert got.equals(delta * before_later[n]), f"section {n} was not propagated"


def test_quick_align_made_first_is_picked_up(field, fake_registration):
    _flicker_setup(field)
    before = field.section.tform.copy()

    field.quickAlign()
    field.setPropagationMode(True)

    assert field.stored_tform.equals(field.section.tform * before.inverted())


def test_quick_align_is_logged(field, fake_registration):
    calls = []
    original = field.series.addLog
    field.series.addLog = lambda *a, **k: (calls.append(a), original(*a, **k))
    _flicker_setup(field)

    field.quickAlign()

    assert (None, field.section.n, "Modify transform") in calls


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

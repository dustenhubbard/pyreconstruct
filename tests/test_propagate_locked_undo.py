"""Tests for two Align-by-correlation propagate fixes.

1. Locked-section bypass in `propagateTo`: the dialog promises "Locked
   sections will not be modified," but the apply loop previously set
   `section.tform` and called `section.save()` on every included section with
   no `align_locked` check -- silently overwriting and persisting alignments
   the user locked. `propagateTo` must skip align-locked sections entirely
   (mirroring the early return `changeTform` does on `align_locked`): no tform
   change, no save, no log entry.

2. Missing undo state: the propagate loop only logged the change (`addLog`);
   it never recorded undo states, so a propagation could not be undone.
   `propagateTo` must record a series-wide undo state plus per-section states
   (the same `SeriesStates` pattern `SeriesIterator` uses) so that a series
   undo restores every modified section's prior transform.

Both are exercised two ways: against duck-typed stubs (as in
test_corr_align_propagate) and end-to-end against the real `shapes1.jser`
fixture with a real `SeriesStates`, verifying on-disk bytes of the locked
section are untouched and that `undoState` restores the prior transforms.

Also confirms the corrAlign composition order (`tform * shift_tform`, i.e.
the field-space shift applied AFTER the existing transform) against a
concrete rotated/scaled transform, where the reversed order visibly differs.
"""
import math
import os
import shutil
import types

import pytest

from PyReconstruct.modules.gui.main import field_widget_4_data as fw
from PyReconstruct.modules.datatypes import Transform

from test_corr_align_propagate import _prop_stub, _patch_corr, _corr_stub

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


def _patch_confirm(monkeypatch, answer):
    calls = []
    monkeypatch.setattr(
        fw, "notifyConfirm",
        lambda *a, **k: (calls.append(a), answer)[1],
    )
    return calls


# ---------------------------------------------------------------------------
# stub-level: locked sections are skipped
# ---------------------------------------------------------------------------

def test_propagate_skips_locked_section(monkeypatch):
    """A locked section inside the range keeps its tform, is never saved, and
    gets no undo/log entry -- while unlocked sections still propagate."""
    confirms = _patch_confirm(monkeypatch, True)
    base = [1, 0, 0, 0, 1, 0]
    stub, sections = _prop_stub(
        monkeypatch, {n: base for n in (1, 2, 3, 4, 5)},
        current_section=3, locked=(4,),
    )
    dx, dy = 2.5, 1.0
    fw.FieldWidgetData.changeTform(
        stub, stub.section.tform * Transform([1, 0, dx, 0, 1, dy])
    )

    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    assert len(confirms) == 1, "user is warned exactly once about locked sections"
    # locked section 4: untouched and NOT re-saved
    assert sections[4].tform.equals(Transform(list(base)))
    assert sections[4].save_count == 0
    assert 4 not in stub.propagated_sections
    # unlocked section 5: shifted and saved
    assert sections[5].tform.equals(Transform([1, 0, dx, 0, 1, dy]))
    assert sections[5].save_count == 1
    assert 5 in stub.propagated_sections
    # undo recorded only for the modified section
    assert stub.series_states.series_state_count == 1
    assert stub.series_states.section_undos == [5]
    assert stub.series_states[4].recorded == []


def test_propagate_declined_on_locked_leaves_everything_untouched(monkeypatch):
    """Answering 'no' to the locked-section prompt aborts the propagation."""
    _patch_confirm(monkeypatch, False)
    base = [1, 0, 0, 0, 1, 0]
    stub, sections = _prop_stub(
        monkeypatch, {n: base for n in (1, 2, 3)},
        current_section=1, locked=(2,),
    )
    stub.stored_tform = Transform([1, 0, 2.5, 0, 1, 1.0])

    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    for n in (2, 3):
        assert sections[n].tform.equals(Transform(list(base)))
        assert sections[n].save_count == 0
    assert stub.series_states.series_state_count == 0
    assert stub.series_states.section_undos == []


def test_propagate_records_undo_state_per_modified_section(monkeypatch):
    """Every modified section gets a recorded state tied to a series undo."""
    base = [1, 0, 0, 0, 1, 0]
    stub, sections = _prop_stub(
        monkeypatch, {n: base for n in (1, 2, 3, 4)}, current_section=1,
    )
    dx, dy = 2.5, 1.0
    stub.stored_tform = Transform([1, 0, dx, 0, 1, dy])

    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    assert stub.series_states.series_state_count == 1
    assert stub.series_states.section_undos == [2, 3, 4]
    for n in (2, 3, 4):
        recorded = stub.series_states[n].recorded
        assert len(recorded) == 1
        # the state is recorded after the modification (SeriesIterator pattern:
        # SectionStates.addState pushes the pre-mod snapshot internally)
        assert recorded[0].equals(Transform([1, 0, dx, 0, 1, dy]))


# ---------------------------------------------------------------------------
# end-to-end: real series, real SeriesStates
# ---------------------------------------------------------------------------

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


def _set_locked(series, snum, locked):
    section = series.loadSection(snum)
    section.align_locked = locked
    section.save()


def _real_stub(monkeypatch, series, current_section, stored_tform):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    series.current_section = current_section
    cur = series.loadSection(current_section)
    stub = types.SimpleNamespace(
        section=cur,
        section_layer=types.SimpleNamespace(section=cur),
        series=series,
        series_states=SeriesStates(series),
        propagate_tform=True,
        stored_tform=stored_tform,
        propagated_sections={current_section},
    )
    stub.generateView = lambda *a, **k: None
    stub.saveState = lambda *a, **k: None
    stub.reload = lambda *a, **k: None
    monkeypatch.setattr(
        fw, "getProgbar",
        lambda *a, **k: types.SimpleNamespace(
            setValue=lambda v: None, close=lambda: None
        ),
    )
    return stub


def test_real_series_locked_section_untouched_and_not_resaved(
        monkeypatch, tmp_path):
    """End-to-end on shapes1.jser: propagating across a range containing a
    locked section leaves that section's tform AND its on-disk file untouched,
    while the unlocked sections in range are modified and persisted."""
    series = _load_series(tmp_path)
    _patch_confirm(monkeypatch, True)

    # fixture sections 0-4 are all locked; unlock all but section 2
    for n in (0, 1, 3, 4):
        _set_locked(series, n, False)

    orig_tforms = {
        n: series.loadSection(n).tform.copy() for n in series.sections
    }
    locked_fp = os.path.join(series.getwdir(), series.sections[2])
    with open(locked_fp, "rb") as f:
        locked_bytes_before = f.read()

    stored = Transform([1, 0, 0.5, 0, 1, -0.25])
    stub = _real_stub(monkeypatch, series, current_section=1,
                      stored_tform=stored)
    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    # locked section 2: same tform on a fresh load, file bytes identical
    assert series.loadSection(2).tform.equals(orig_tforms[2])
    with open(locked_fp, "rb") as f:
        assert f.read() == locked_bytes_before, \
            "locked section file must not be re-saved"
    assert 2 not in stub.propagated_sections

    # unlocked sections 3 and 4: persisted stored * original
    for n in (3, 4):
        expected = stored * orig_tforms[n]
        assert series.loadSection(n).tform.equals(expected)

    # sections before the current one: untouched
    assert series.loadSection(0).tform.equals(orig_tforms[0])

    series.close()


def test_real_series_propagation_is_undoable(monkeypatch, tmp_path):
    """End-to-end: a series undo after propagateTo restores the prior
    transforms of every section the propagation modified."""
    series = _load_series(tmp_path)
    _patch_confirm(monkeypatch, True)

    for n in series.sections:
        _set_locked(series, n, False)

    orig_tforms = {
        n: series.loadSection(n).tform.copy() for n in series.sections
    }

    stored = Transform([1, 0, 0.5, 0, 1, -0.25])
    stub = _real_stub(monkeypatch, series, current_section=1,
                      stored_tform=stored)
    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    # propagation happened (sanity)
    for n in (2, 3, 4):
        assert series.loadSection(n).tform.equals(stored * orig_tforms[n])

    # a series undo must now be available and restore the prior transforms
    can_3D, _, _ = stub.series_states.canUndo()
    assert can_3D, "propagation must leave an undoable series state"
    stub.series_states.undoState()

    for n in series.sections:
        assert series.loadSection(n).tform.equals(orig_tforms[n]), \
            f"undo must restore section {n}'s prior transform"

    series.close()


# ---------------------------------------------------------------------------
# corrAlign composition order on a rotated/scaled transform
# ---------------------------------------------------------------------------

def test_corr_align_composition_on_rotated_scaled_tform(monkeypatch):
    """For a rotated+scaled section, corrAlign must produce
    section.tform * shift (field-space shift applied AFTER the transform:
    A * B maps p -> B(A(p)) here) -- demonstrably NOT shift * tform."""
    _patch_corr(monkeypatch, offset=(10, -4))
    # scaling=2, mag=0.5 -> shift = (2.5, 1.0)
    dx, dy = 2.5, 1.0
    # rotation by 30 degrees, scaled by 2, translated
    c, s = 2 * math.cos(math.pi / 6), 2 * math.sin(math.pi / 6)
    base = [c, -s, 1.5, s, c, -0.5]
    stub = _corr_stub(base, mag=0.5, scaling=2.0)
    tform = Transform(list(base))
    shift = Transform([1, 0, dx, 0, 1, dy])

    fw.FieldWidgetData.corrAlign(stub)

    assert len(stub.changeTform_calls) == 1
    got = stub.changeTform_calls[0]
    assert got.equals(tform * shift), "shift must compose AFTER the tform"
    # the reversed (buggy) order is genuinely different here...
    assert not got.equals(shift * tform)
    # ...and only the correct order shifts mapped points by exactly (dx, dy)
    for p in [(0.0, 0.0), (1.0, 2.0), (-3.0, 0.25)]:
        bx, by = tform.map(*p)
        gx, gy = got.map(*p)
        assert gx == pytest.approx(bx + dx)
        assert gy == pytest.approx(by + dy)

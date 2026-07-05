"""Tests for #90: Align-by-correlation records its shift so it can be
propagated across a section range.

`corrAlign` computes an FFT cross-correlation shift and now routes it through
`changeTform` (the same recording path a manual transform uses) instead of
assigning `section.tform` directly. When propagation recording is active the
shift is captured in `stored_tform` and replayed across a range by
`propagateTo`, exactly like a manual translate.

The correlation shift is composed as `section.tform * shift_tform` -- the
existing tform post-multiplied by a field-space translation (the shipped H3
transform-order fix). That is bit-for-bit the same transform a manual translate
of the same (dx, dy) produces, so it propagates with identical semantics.

The methods are exercised against duck-typed stubs (as in
test_affine_align_guard) plus the real `Transform`, `changeTform`, and
`propagateTo`, so no Qt event loop is required.
"""
import types

import pytest

from PyReconstruct.modules.gui.main import field_widget_4_data as fw
from PyReconstruct.modules.datatypes import Transform


# --- corrAlign routing -----------------------------------------------------

def _corr_stub(tform_list, *, mag, scaling, locked=False, b_layer=True):
    section = types.SimpleNamespace(
        align_locked=locked,
        mag=mag,
        tform=Transform(list(tform_list)),
        n=3,
    )
    stub = types.SimpleNamespace(
        section=section,
        section_layer=types.SimpleNamespace(
            section=section,
            generateImageArray=lambda dim, window: None,
        ),
        b_section_layer=(
            types.SimpleNamespace(generateImageArray=lambda dim, window: None)
            if b_layer else None
        ),
        series=types.SimpleNamespace(window=(0, 0, 1, 1)),
        pixmap_dim=(4, 4),
        scaling=scaling,
        changeTform_calls=[],
    )
    stub.changeTform = lambda t: stub.changeTform_calls.append(t)
    return stub


def _patch_corr(monkeypatch, offset):
    notified = []
    monkeypatch.setattr(fw, "notify", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(
        fw, "cv2",
        types.SimpleNamespace(cvtColor=lambda a, code: a, COLOR_RGB2BGR=0),
    )
    monkeypatch.setattr(fw, "correlate", lambda a, b: offset)
    return notified


def test_corr_align_routes_shift_through_changeTform(monkeypatch):
    """The computed field-space shift is post-composed onto the existing tform
    and handed to changeTform (not written to section.tform directly)."""
    _patch_corr(monkeypatch, offset=(10, -4))
    # scaling=2, mag=0.5  ->  shift_x = 10/2*0.5 = 2.5 ; shift_y = -(-4/2*0.5) = 1.0
    base = [2, 0, 3, 0, 3, -7]
    stub = _corr_stub(base, mag=0.5, scaling=2.0)
    original_tform = stub.section.tform

    fw.FieldWidgetData.corrAlign(stub)

    assert len(stub.changeTform_calls) == 1, "corrAlign must record via changeTform"
    got = stub.changeTform_calls[0]
    # field-space post-shift only touches the translation components
    expected = Transform([2, 0, 3 + 2.5, 0, 3, -7 + 1.0])
    assert got.equals(expected)
    # equals section.tform * shift_tform (the shipped H3 ordering)
    shift = Transform([1, 0, 2.5, 0, 1, 1.0])
    assert got.equals(original_tform * shift)
    # section.tform is NOT mutated directly by corrAlign anymore
    assert stub.section.tform is original_tform


def test_corr_align_no_b_section_is_noop(monkeypatch):
    _patch_corr(monkeypatch, offset=(10, -4))
    stub = _corr_stub([1, 0, 0, 0, 1, 0], mag=1.0, scaling=1.0, b_layer=False)
    fw.FieldWidgetData.corrAlign(stub)
    assert stub.changeTform_calls == []


def test_corr_align_locked_section_is_noop(monkeypatch):
    notified = _patch_corr(monkeypatch, offset=(10, -4))
    stub = _corr_stub([1, 0, 0, 0, 1, 0], mag=1.0, scaling=1.0, locked=True)
    fw.FieldWidgetData.corrAlign(stub)
    assert stub.changeTform_calls == []
    assert notified, "a locked section should warn the user"


# --- capture: correlation shift == manual translate ------------------------

def _record_stub(base_tform):
    section = types.SimpleNamespace(
        align_locked=False, tform=Transform(list(base_tform)), n=1
    )
    stub = types.SimpleNamespace(
        section=section,
        section_layer=types.SimpleNamespace(section=section),
        series=types.SimpleNamespace(addLog=lambda *a, **k: None),
        propagate_tform=True,
        stored_tform=Transform.identity(),
    )
    stub.generateView = lambda *a, **k: None
    stub.saveState = lambda *a, **k: None
    return stub


def test_capture_equivalent_to_manual_translate():
    """Recording a correlation shift yields the same stored_tform as recording
    an equivalent manual translate of the same (dx, dy)."""
    base = [2, 0, 3, 0, 3, -7]
    dx, dy = 2.5, 1.0

    # correlation path: section.tform * field-space shift
    corr = _record_stub(base)
    corr_new = corr.section.tform * Transform([1, 0, dx, 0, 1, dy])
    fw.FieldWidgetData.changeTform(corr, corr_new)

    # manual translate path (see translateTform): add dx, dy to translation
    man = _record_stub(base)
    m = man.section.tform.getList()
    m[2] += dx
    m[5] += dy
    fw.FieldWidgetData.changeTform(man, Transform(m))

    # the applied transforms are identical...
    assert corr.section.tform.equals(man.section.tform)
    # ...and so is the captured stored_tform that propagation replays
    assert corr.stored_tform.equals(man.stored_tform)
    # captured delta is the conjugated change: new * current.inverted()
    expected_delta = corr_new * Transform(list(base)).inverted()
    assert corr.stored_tform.equals(expected_delta)


# --- replay: propagateTo across a range ------------------------------------

def _prop_stub(monkeypatch, base_tforms, current_section):
    """Build a stub with an in-memory set of sections and the real
    changeTform/propagateTo wired up."""
    sections = {
        n: types.SimpleNamespace(
            n=n, align_locked=False, tform=Transform(list(t)), save=lambda: None
        )
        for n, t in base_tforms.items()
    }
    cur = sections[current_section]
    stub = types.SimpleNamespace(
        section=cur,
        section_layer=types.SimpleNamespace(section=cur),
        series=types.SimpleNamespace(
            sections=sections,
            current_section=current_section,
            loadSection=lambda snum: sections[snum],
            addLog=lambda *a, **k: None,
        ),
        propagate_tform=True,
        stored_tform=Transform.identity(),
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
    return stub, sections


def test_propagate_to_end_same_base_is_field_shift(monkeypatch):
    """Sections sharing the current section's base tform get the identical
    field-space shift when the recorded correlation align propagates forward."""
    base = [2, 0, 3, 0, 3, -7]
    dx, dy = 2.5, 1.0
    stub, sections = _prop_stub(
        monkeypatch, {n: base for n in (1, 2, 3, 4, 5)}, current_section=3
    )

    # record the correlation shift on section 3
    new = stub.section.tform * Transform([1, 0, dx, 0, 1, dy])
    fw.FieldWidgetData.changeTform(stub, new)

    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    shifted = Transform([2, 0, 3 + dx, 0, 3, -7 + dy])
    # forward sections shifted; current section already shifted by changeTform
    for n in (3, 4, 5):
        assert sections[n].tform.equals(shifted), f"section {n} should be shifted"
    # sections before current are untouched
    for n in (1, 2):
        assert sections[n].tform.equals(Transform(list(base)))


def test_propagate_to_start_direction(monkeypatch):
    base = [2, 0, 3, 0, 3, -7]
    dx, dy = 2.5, 1.0
    stub, sections = _prop_stub(
        monkeypatch, {n: base for n in (1, 2, 3, 4, 5)}, current_section=3
    )
    new = stub.section.tform * Transform([1, 0, dx, 0, 1, dy])
    fw.FieldWidgetData.changeTform(stub, new)

    fw.FieldWidgetData.propagateTo(stub, to_end=False)

    shifted = Transform([2, 0, 3 + dx, 0, 3, -7 + dy])
    for n in (1, 2, 3):
        assert sections[n].tform.equals(shifted)
    for n in (4, 5):  # forward sections untouched when propagating to start
        assert sections[n].tform.equals(Transform(list(base)))


def test_propagate_conjugates_for_differing_base(monkeypatch):
    """A section with a *different* base tform receives the stored delta mapped
    through its own tform (stored_tform * section.tform), matching the existing
    manual-propagation semantics -- NOT a naive identical field shift.

    Current section base scales x2/y3; target section 4 is identity. The stored
    delta is a pure translation of (1.25, 1/3), so section 4 shifts by that,
    which differs from the current section's (2.5, 1.0) field shift.
    """
    dx, dy = 2.5, 1.0
    stub, sections = _prop_stub(
        monkeypatch,
        {1: [2, 0, 3, 0, 3, -7], 2: [2, 0, 3, 0, 3, -7],
         3: [2, 0, 3, 0, 3, -7], 4: [1, 0, 0, 0, 1, 0]},
        current_section=3,
    )
    new = stub.section.tform * Transform([1, 0, dx, 0, 1, dy])
    fw.FieldWidgetData.changeTform(stub, new)

    stored = stub.stored_tform
    fw.FieldWidgetData.propagateTo(stub, to_end=True)

    # section 4 (identity base) == stored * identity == stored (a pure translate)
    assert sections[4].tform.equals(stored * Transform([1, 0, 0, 0, 1, 0]))
    assert sections[4].tform.equals(Transform([1, 0, 1.25, 0, 1, 1.0 / 3.0]))
    # and it is NOT the naive field shift the current section received
    assert not sections[4].tform.equals(Transform([1, 0, dx, 0, 1, dy]))

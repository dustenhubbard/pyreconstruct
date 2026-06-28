"""Regression test for affineAlign's missing early return.

Same bug class as the setSeriesMag / validation-guard fixes: affineAlign warns
when fewer than 3 traces are selected ("Please select 3 or more traces for
aligning.") but (before the fix) lacked a `return`. The sibling
`if alen != blen` guard only catches *unequal* counts, so selecting an equal
but insufficient number of traces on each section (0&0, 1&1, 2&2) slipped
through: with 0 traces it raised IndexError on `a_traces[0]`, and with 1-2 it
fell through to estimateTform/changeTform, writing a degenerate (NaN) transform
onto the section. The method is exercised against duck-typed stubs so no real
FieldWidget / Qt event loop is required.
"""
import types
import pytest

from PyReconstruct.modules.gui.main import field_widget_4_data as fw


_SENTINEL_TFORM = object()


class _Tform:
    @staticmethod
    def map(points):
        return points


def _make_traces(n, name="x"):
    return [types.SimpleNamespace(name=name, points=[(0.0, 0.0)]) for _ in range(n)]


def _make_stub(a_n, b_n):
    section = types.SimpleNamespace(
        selected_traces=_make_traces(a_n), align_locked=False
    )
    b_section = types.SimpleNamespace(
        selected_traces=_make_traces(b_n), tform=_Tform()
    )
    stub = types.SimpleNamespace(
        section=section, b_section=b_section, changeTform_calls=[]
    )
    stub.changeTform = lambda tform: stub.changeTform_calls.append(tform)
    return stub


def _patch(monkeypatch):
    notified = []
    est_calls = []

    def fake_est(p1, p2):
        est_calls.append((p1, p2))
        return _SENTINEL_TFORM

    monkeypatch.setattr(fw, "notify", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(fw, "centroid", lambda points: (0.0, 0.0))
    monkeypatch.setattr(fw.Transform, "estimateTform", staticmethod(fake_est))
    return notified, est_calls


@pytest.mark.parametrize("n", [0, 1, 2])
def test_too_few_equal_traces_aborts(monkeypatch, n):
    """Equal but <3 traces on each section must warn and NOT apply a transform.

    The `alen != blen` guard does not catch these (counts are equal), so before
    the fix n=0 raised IndexError and n in (1, 2) applied a degenerate transform.
    """
    notified, est_calls = _patch(monkeypatch)
    stub = _make_stub(n, n)

    fw.FieldWidgetData.affineAlign(stub)  # must not raise

    assert notified, "should warn when fewer than 3 traces are selected"
    assert est_calls == [], "must not estimate a transform from <3 point pairs"
    assert stub.changeTform_calls == [], "must not apply a transform on rejected input"


def test_valid_three_traces_still_aligns(monkeypatch):
    """Three equal, same-named traces still estimate and apply the transform
    (guards against the fix over-aborting on valid input)."""
    notified, est_calls = _patch(monkeypatch)
    stub = _make_stub(3, 3)

    fw.FieldWidgetData.affineAlign(stub)

    assert len(est_calls) == 1, "valid input should estimate the transform"
    assert stub.changeTform_calls == [_SENTINEL_TFORM], "valid transform should be applied"

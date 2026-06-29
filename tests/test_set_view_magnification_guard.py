"""Regression test for setViewMagnification accepting a non-positive value.

The view-magnification dialog parses the entered text with float(), which
accepts "0" and negatives. Only ValueError is caught, so 0.0 flowed into
setView, where ``factor = mag * screen_mag`` becomes 0 and the window
dimensions are computed as w / 0 -> ZeroDivisionError (a negative value would
silently corrupt the window). Reject a non-positive magnification, matching the
existing silent return on unparseable input. Exercised against a duck-typed
stub with QInputDialog monkeypatched.
"""
import types

import pytest

from PyReconstruct.modules.gui.main import field_widget_7_view as v


def _patch_input(monkeypatch, text, confirmed=True):
    monkeypatch.setattr(
        v, "QInputDialog",
        types.SimpleNamespace(getText=lambda *a, **k: (text, confirmed)),
    )


def _stub():
    calls = []
    stub = types.SimpleNamespace(
        series=types.SimpleNamespace(screen_mag=0.01),
        setView=lambda m: calls.append(m),
    )
    return stub, calls


@pytest.mark.parametrize("text", ["0", "-5"])
def test_non_positive_view_mag_is_rejected(monkeypatch, text):
    _patch_input(monkeypatch, text)
    stub, calls = _stub()

    v.FieldWidgetView.setViewMagnification(stub)

    assert calls == [], "a non-positive view magnification must not reach setView"


def test_valid_view_mag_is_applied(monkeypatch):
    _patch_input(monkeypatch, "100")
    stub, calls = _stub()

    v.FieldWidgetView.setViewMagnification(stub)

    assert calls == [100.0]


def test_cancelled_dialog_does_nothing(monkeypatch):
    _patch_input(monkeypatch, "100", confirmed=False)
    stub, calls = _stub()

    v.FieldWidgetView.setViewMagnification(stub)

    assert calls == []

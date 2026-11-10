"""Regression test for setViewMagnification accepting a non-positive value.

The view-magnification dialog parses the entered text with float(), which
accepts "0" and negatives. Only ValueError is caught, so 0.0 flowed into
setView, where ``factor = mag * screen_mag`` becomes 0 and the window
dimensions are computed as w / 0 -> ZeroDivisionError (a negative value would
silently corrupt the window). Reject a non-positive magnification, matching the
existing silent return on unparseable input. Exercised against a duck-typed
stub with QInputDialog monkeypatched, then on a live MainWindow for the
nonfinite and underflowing values.
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


# The same dialog on a live MainWindow.
# float() also accepts "nan", "inf" and overflow such as "1e309", and none of
# them is <= 0, so they reached setView and wrote NaN or zero sizes into
# series.window. A value so small that the scale rounds to zero divided by
# zero in setView, and one just above that made the window infinite.


def _ask_live(main_window, qapp, monkeypatch, text, confirmed=True):
    """Run the View magnification... slot with the dialog answered.

    The slot is called directly, so an exception fails the test instead of
    opening the app's error dialog. generateView is recorded, not run, so a
    bad window never reaches Qt; the test reads series.window instead.
    """
    _patch_input(monkeypatch, text, confirmed)
    field = main_window.field
    drawn = []
    monkeypatch.setattr(field, "generateView", lambda *a, **k: drawn.append(1))
    before = list(field.series.window)
    field.setViewMagnification()
    qapp.processEvents()
    return before, list(field.series.window), drawn


@pytest.mark.gui
@pytest.mark.parametrize(
    "text",
    ["nan", "inf", "1e309", "-inf", "0", "-5", "5e-324", "1e-320", "many"],
)
def test_live_view_mag_rejects_bad_input(main_window, qapp, monkeypatch, text):
    before, after, drawn = _ask_live(main_window, qapp, monkeypatch, text)

    assert after == before, f"{text!r} must leave the window as it was"
    assert drawn == []


@pytest.mark.gui
def test_live_view_mag_cancel_leaves_the_window(main_window, qapp, monkeypatch):
    before, after, drawn = _ask_live(
        main_window, qapp, monkeypatch, "100", confirmed=False
    )

    assert after == before
    assert drawn == []


@pytest.mark.gui
def test_live_view_mag_applies_a_valid_value(main_window, qapp, monkeypatch):
    field = main_window.field
    screen_mag = field.series.screen_mag
    assert screen_mag > 0
    mag = round(2 / screen_mag, 6)

    before, after, drawn = _ask_live(main_window, qapp, monkeypatch, str(mag))

    factor = mag * screen_mag
    assert after[2] == pytest.approx(before[2] / factor)
    assert after[3] == pytest.approx(before[3] / factor)
    # the center stays where it was
    assert after[0] + after[2] / 2 == pytest.approx(before[0] + before[2] / 2)
    assert after[1] + after[3] / 2 == pytest.approx(before[1] + before[3] / 2)
    assert drawn == [1]


@pytest.mark.gui
@pytest.mark.parametrize("mag", [5e-324, 1e-320, float("nan"), float("inf")])
def test_live_set_view_leaves_the_window_for_an_unusable_scale(
    main_window, monkeypatch, mag
):
    """setView itself: a scale that rounds to zero raised ZeroDivisionError,
    and one that overflows the size made the window infinite."""
    field = main_window.field
    drawn = []
    monkeypatch.setattr(field, "generateView", lambda *a, **k: drawn.append(1))
    before = list(field.series.window)

    field.setView(mag)

    assert list(field.series.window) == before
    assert drawn == []


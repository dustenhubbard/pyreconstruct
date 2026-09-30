"""Calibrate refuses a length of zero or less, and anything non-finite.

Before the fix, entering 0 in the calibrate prompt set the mag to 0.0 on every
section and saved every point in the series as (0, 0). A negative length gave a
negative mag and mirrored every point.
"""
import types

import pytest
from PySide6.QtWidgets import QInputDialog

from PyReconstruct.modules.gui.main import main_window as mw
from PyReconstruct.modules.gui.main.field_widget_4_data import FieldWidgetData


BAD_LENGTHS = ["0", "-0", "-1", "-0.5", "nan", "inf", "-inf", "abc", ""]


def _stub_window(monkeypatch, text):
    notified = []
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(
        mw, "QInputDialog",
        types.SimpleNamespace(getText=lambda *a, **k: (text, True)),
    )
    field_calls = []

    class _Field:
        section = types.SimpleNamespace(
            selected_traces=[types.SimpleNamespace(name="a")]
        )

        def calibrateMag(self, trace_lengths):
            field_calls.append(trace_lengths)

    stub = types.SimpleNamespace(saveAllData=lambda: None, field=_Field())
    return stub, notified, field_calls


@pytest.mark.parametrize("text", BAD_LENGTHS)
def test_bad_length_is_refused_with_a_message(monkeypatch, text):
    stub, notified, field_calls = _stub_window(monkeypatch, text)

    mw.MainWindow.calibrateMag(stub)

    assert notified, f"{text!r} should be refused with a message"
    assert field_calls == [], f"{text!r} must not reach the calibration"


def test_positive_length_still_calibrates(monkeypatch):
    stub, notified, field_calls = _stub_window(monkeypatch, "2.5")

    mw.MainWindow.calibrateMag(stub)

    assert notified == []
    assert field_calls == [{"a": 2.5}]


@pytest.mark.parametrize("mag", [0.0, -0.002, float("nan"), float("inf")])
def test_field_set_mag_refuses_before_touching_a_section(mag):
    touched = []

    def enumerate_sections(**kwargs):
        touched.append(True)
        return iter(())

    stub = types.SimpleNamespace(
        series=types.SimpleNamespace(enumerateSections=enumerate_sections)
    )

    with pytest.raises(ValueError):
        FieldWidgetData.setMag(stub, mag)
    assert touched == []


def _series_snapshot(series):
    mags = {}
    points = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        mags[snum] = section.mag
        points[snum] = [list(t.points) for t in section.tracesAsList()]
    return mags, points


@pytest.mark.parametrize("text", ["0", "-1"])
def test_zero_or_negative_leaves_the_series_on_disk_alone(
    main_window, monkeypatch, text
):
    win = main_window
    series = win.series
    snum = next(
        s for s in sorted(series.sections)
        if series.loadSection(s).tracesAsList()
    )
    win.changeSection(snum)
    section = win.field.section
    section.selected_traces = [section.tracesAsList()[0]]
    win.saveAllData()
    before = _series_snapshot(series)

    notified = []
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: (text, True))
    )
    win.calibrateMag()

    assert notified
    assert _series_snapshot(series) == before
    win.field.generateView()

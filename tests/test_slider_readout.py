"""Every QuickDialog slider must say what it is setting.

A bare ``QSlider`` puts a handle on a blank groove and shows no number, so the
three sliders in Series > Options were unreadable: the 3D detail slider, the
scale bar size slider, and the CPU usage slider whose original complaint was
that a setting the user believed was four workers ran eight, with nothing on
screen to check it against.

``SliderWidget`` pairs the slider with tick marks and a live readout in the
caller's own units. These tests pin:

1. the readout tracks the value, on construction and on every change;
2. ticks are on, at a spacing that suits the range;
3. the readout speaks the caller's units, not the raw groove position;
4. what each of the three real callers actually passes, built through the real
   ``AllOptionsDialog`` rather than by reading the structure literal;
5. the scale bar slider round-trips the stored 20-100 value exactly. It used to
   be squeezed onto an 0-100 groove on the way in and squeezed back on the way
   out, which was lossy at the top of the range: 99 came back as 98.

The units are read from the code that consumes each option, not invented:
``3D_xy_res`` is ``vres_percent`` in ``objects_3D.generateTrimesh``;
``scale_bar_width`` is divided by 100 and multiplied by the field width in
``mouse_palette``; ``cpu_max`` goes through ``determine_cpus``, which is a
percentage of ``os.cpu_count()``.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.backend.func.utils import determine_cpus
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import (
    AllOptionsDialog, cpuSliderReadout,
)
from PyReconstruct.modules.gui.dialog.helper import (
    SliderWidget, defaultTickInterval,
)
from PyReconstruct.modules.gui.dialog.quick_dialog import getLayout

pytestmark = pytest.mark.gui

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


def _series(tmp_path):
    """A real series backed by an in-memory settings store (no QSettings I/O)."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    os.makedirs(tmp_path, exist_ok=True)
    fp = os.path.join(str(tmp_path), "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def _slider(dlg, widget_name):
    """The one SliderWidget inside a named option widget, via the real dialog."""
    w = dlg.all_widgets[widget_name]
    sliders = [f.widget for f in w.inputs if f.type == "slider"]
    assert len(sliders) == 1, (widget_name, sliders)
    return sliders[0]


# --- the widget itself -------------------------------------------------------

def test_readout_shows_the_starting_value(qapp):
    w = SliderWidget(None, value=37)
    assert w.text() == "37"


def test_readout_tracks_the_value(qapp):
    w = SliderWidget(None, value=0)
    seen = []
    for v in (10, 55, 99, 0):
        w.setValue(v)
        seen.append(w.text())
    assert seen == ["10", "55", "99", "0"]


def test_readout_tracks_the_slider_itself_not_just_setValue(qapp):
    """Driving the inner QSlider directly (as a mouse drag does) must update
    the readout, i.e. the connection is on valueChanged and not on the wrapper."""
    w = SliderWidget(None, value=0)
    w.slider.setValue(64)
    assert w.text() == "64"
    assert w.value() == 64


def test_ticks_are_on(qapp):
    from PySide6.QtWidgets import QSlider
    w = SliderWidget(None, value=0)
    assert w.slider.tickPosition() == QSlider.TicksBelow
    assert w.slider.tickInterval() > 0


def test_explicit_tick_interval_wins(qapp):
    w = SliderWidget(None, value=50, tick_interval=25)
    assert w.slider.tickInterval() == 25


def test_default_tick_interval_suits_the_range():
    # roughly ten ticks across the groove, rounded to a number a person would pick
    assert defaultTickInterval(0, 100) == 10
    assert defaultTickInterval(20, 100) == 10
    assert defaultTickInterval(0, 10) == 1
    assert defaultTickInterval(0, 1000) == 100
    # a degenerate range must not divide by zero or ask for a zero interval
    assert defaultTickInterval(50, 50) == 1


def test_suffix_is_shown(qapp):
    w = SliderWidget(None, value=42, suffix="%")
    assert w.text() == "42%"
    w.setValue(7)
    assert w.text() == "7%"


def test_fmt_overrides_suffix(qapp):
    w = SliderWidget(None, value=3, suffix="%", fmt=lambda v: f"<{v}>")
    assert w.text() == "<3>"


def test_range_is_honored_and_clamps(qapp):
    w = SliderWidget(None, value=25, minimum=20, maximum=100)
    assert w.slider.minimum() == 20
    assert w.slider.maximum() == 100
    w.setValue(5)                    # below the floor
    assert w.value() == 20
    assert w.text() == "20"


def test_readout_reserves_width_for_the_longest_string(qapp):
    """The slider must not jump sideways when the readout gains a character.

    The readout starts at "x" in both cases; only the widest string the range
    can reach differs, so a wider reservation proves the room was booked for the
    end of the range rather than for the value on screen.
    """
    grow = lambda v: "x" * (v + 1)          # noqa: E731 -- one-line test helper
    narrow = SliderWidget(None, value=0, minimum=0, maximum=5, fmt=grow)
    wide = SliderWidget(None, value=0, minimum=0, maximum=30, fmt=grow)
    assert narrow.text() == wide.text() == "x"
    assert wide.readout.minimumWidth() > narrow.readout.minimumWidth()
    # and the room is enough for the longest string, not just for "x"
    metrics = wide.readout.fontMetrics()
    assert wide.readout.minimumWidth() >= metrics.boundingRect(grow(30)).width()


# --- the spec tuple ----------------------------------------------------------

def _one_slider(structure, qapp):
    _layout, inputs = getLayout(None, structure)
    sliders = [f.widget for f in inputs if f.type == "slider"]
    assert len(sliders) == 1
    return sliders[0]


def test_bare_spec_still_works(qapp):
    """An existing caller that passes only a value keeps its 0-100 range."""
    w = _one_slider([[("slider", 40)]], qapp)
    assert (w.slider.minimum(), w.slider.maximum()) == (0, 100)
    assert w.value() == 40
    assert w.text() == "40"


def test_spec_with_no_params_defaults_to_zero(qapp):
    w = _one_slider([[("slider",)]], qapp)
    assert w.value() == 0


def test_tick_interval_param_still_works(qapp):
    """The three-element form that already shipped keeps its meaning."""
    w = _one_slider([[("slider", 50, 25)]], qapp)
    assert w.slider.tickInterval() == 25


def test_options_dict_may_follow_the_tick_interval(qapp):
    w = _one_slider([[("slider", 50, 25, {"suffix": " units"})]], qapp)
    assert w.slider.tickInterval() == 25
    assert w.text() == "50 units"


def test_options_dict_may_replace_the_tick_interval(qapp):
    """A caller that wants units but no opinion on ticks skips the int."""
    w = _one_slider([[("slider", 50, {"minimum": 20, "suffix": "%"})]], qapp)
    assert w.slider.minimum() == 20
    assert w.text() == "50%"
    assert w.slider.tickInterval() == defaultTickInterval(20, 100)


def test_slider_response_is_still_the_number(qapp):
    """getResponse must keep returning a plain int, so every existing setOption
    closure reads the same thing it always did."""
    w = _one_slider([[("slider", 63)]], qapp)
    _layout, inputs = getLayout(None, [[("slider", 63)]])
    field = [f for f in inputs if f.type == "slider"][0]
    response, ok = field.getResponse()
    assert ok is True
    assert response == 63
    assert isinstance(response, int)


# --- the CPU readout ---------------------------------------------------------

def test_cpu_readout_names_workers_and_percentage():
    total = os.cpu_count() or 1
    assert cpuSliderReadout(100) == f"100% ({determine_cpus(100)} of {total} workers)"
    assert determine_cpus(100) == total          # the premise of the sentence


def test_cpu_readout_agrees_with_the_converter_for_every_setting():
    """The number on screen must be the number the converter will launch."""
    total = os.cpu_count() or 1
    for percent in range(0, 101):
        assert cpuSliderReadout(percent) == (
            f"{percent}% ({determine_cpus(percent)} of {total} workers)"
        )


# --- what the three real callers pass ----------------------------------------

def test_3d_detail_slider_is_a_percentage(qapp, tmp_path):
    series = _series(tmp_path)
    series.setOption("3D_xy_res", 30)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _slider(dlg, "smoothing_3D")
        assert (w.slider.minimum(), w.slider.maximum()) == (0, 100)
        assert w.value() == 30
        assert w.text() == "30%"
        w.setValue(80)
        assert w.text() == "80%"
    finally:
        dlg.deleteLater()


def test_3d_detail_slider_roundtrips(qapp, tmp_path):
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = dlg.all_widgets["smoothing_3D"]
        _slider(dlg, "smoothing_3D").setValue(65)
        assert w.accept(close=False)
        w.set()
        assert series.getOption("3D_xy_res") == 65
    finally:
        dlg.deleteLater()


def test_scale_bar_slider_carries_the_stored_range(qapp, tmp_path):
    series = _series(tmp_path)
    series.setOption("scale_bar_width", 45)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _slider(dlg, "scale_bar")
        assert (w.slider.minimum(), w.slider.maximum()) == (20, 100)
        assert w.value() == 45           # the stored number, not a remapped one
        assert w.text() == "45%"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("stored", list(range(20, 101)))
def test_scale_bar_slider_roundtrips_exactly(qapp, tmp_path, stored):
    """Open the dialog on a stored width and apply it unchanged: the value must
    come back identical, for every value the option can hold.

    The old 0-100 remap failed this for 60 of the 81 values, including the
    shipped default of 25, which came back as 24. Measured against origin/main's
    arithmetic: (stored - 20) / 80 * 100 in, int(v / 100 * 80 + 20) out, with the
    slider truncating the float in between."""
    series = _series(tmp_path)
    series.setOption("scale_bar_width", stored)
    dlg = AllOptionsDialog(None, series)
    try:
        w = dlg.all_widgets["scale_bar"]
        assert _slider(dlg, "scale_bar").value() == stored
        assert w.accept(close=False)
        w.set()
        assert series.getOption("scale_bar_width") == stored
    finally:
        dlg.deleteLater()


def test_scale_bar_slider_stores_what_the_user_moved_it_to(qapp, tmp_path):
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = dlg.all_widgets["scale_bar"]
        _slider(dlg, "scale_bar").setValue(63)
        assert w.accept(close=False)
        w.set()
        assert series.getOption("scale_bar_width") == 63
    finally:
        dlg.deleteLater()


def test_cpu_slider_shows_workers(qapp, tmp_path):
    series = _series(tmp_path)
    series.setOption("cpu_max", 50)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _slider(dlg, "computation")
        assert (w.slider.minimum(), w.slider.maximum()) == (0, 100)
        assert w.slider.tickInterval() == 25
        assert w.value() == 50
        assert w.text() == cpuSliderReadout(50)
        assert "workers" in w.text()
        w.setValue(100)
        assert w.text() == cpuSliderReadout(100)
    finally:
        dlg.deleteLater()


def test_cpu_slider_roundtrips(qapp, tmp_path):
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = dlg.all_widgets["computation"]
        _slider(dlg, "computation").setValue(75)
        assert w.accept(close=False)
        w.set()
        assert series.getOption("cpu_max") == 75
    finally:
        dlg.deleteLater()


def test_import_overlap_slider_has_ticks(qapp, tmp_path):
    """The series-import overlap slider already showed its number above the
    groove; it must have tick marks too. Built through the real widget."""
    from PySide6.QtWidgets import QSlider
    from PyReconstruct.modules.gui.dialog.import_series import ImportTracesWidget
    current = _series(tmp_path / "cur")
    incoming = _series(tmp_path / "inc")
    w = ImportTracesWidget(None, current, incoming)
    try:
        sliders = w.findChildren(QSlider)
        assert len(sliders) == 1, sliders
        assert sliders[0].tickPosition() == QSlider.TicksBelow
        assert sliders[0].tickInterval() == defaultTickInterval(0, 100)
    finally:
        w.deleteLater()


def test_every_options_slider_has_ticks_and_a_readout(qapp, tmp_path):
    """Sweep the whole dialog: no slider may ship without both."""
    from PySide6.QtWidgets import QSlider
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        found = 0
        for name, widget in dlg.all_widgets.items():
            for field in getattr(widget, "inputs", []) or []:
                if field.type != "slider":
                    continue
                found += 1
                s = field.widget
                assert isinstance(s, SliderWidget), name
                assert s.slider.tickPosition() == QSlider.TicksBelow, name
                assert s.slider.tickInterval() > 0, name
                assert s.text(), name
        assert found == 3, found     # 3D detail, scale bar, CPU usage
    finally:
        dlg.deleteLater()

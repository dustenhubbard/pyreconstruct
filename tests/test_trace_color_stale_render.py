"""Regression tests for stale trace colors in the incremental field render.

Bug: after changing a trace's color, the drawn trace line kept rendering the
OLD color while the selection highlight tracked the NEW color.

Root cause: ``TraceLayer.generateTraceLayer(window_moved=False)`` reuses a
cached ``traces_in_view`` list of trace OBJECTS, reconciled only by
``section.added_traces`` / ``removed_traces``. ``Section.editTraceAttributes``
(the single funnel for color/name/tags/fill edits from the trace dialog, the
trace list, the object list, paste-attributes and bulk/import recolors) does
not mutate in place - it REPLACES the trace with a fresh copy. A table refresh
calls ``section.clearTracking()`` and empties the add/remove lists, after which
an incremental render still holds the old, replaced object and draws its stale
color. The highlight is drawn from the (updated) ``selected_traces`` set, so it
correctly showed the new color - producing the reported mismatch.

Fix: the incremental branch detects any cached trace that is no longer a live
member of its contour and falls back to a full rebuild, so current attributes
are always drawn. Selection-only refreshes stay on the fast path.

These tests drive a real section render headlessly (offscreen Qt) and record
the trace objects actually handed to ``_drawTrace``.
"""
import os
import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

OLD_IS_YELLOW = (255, 255, 0)
NEW_GREEN = (0, 255, 0)


def _series():
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    return Series.openJser(FIXTURE)


def _layer(series, section):
    from PyReconstruct.modules.backend.view.section_layer import SectionLayer
    return SectionLayer(section, series, load_image_layer=False)


def _record_draws(layer):
    """Patch _drawTrace to record (trace, drawn_color, highlighted) per call."""
    calls = []
    orig = type(layer)._drawTrace

    def rec(self, painter, trace, tform, fill_opacity, color=None):
        drawn_color = tuple(color) if color else tuple(trace.color)
        calls.append((trace, drawn_color, trace in self._selected_set))
        return orig(self, painter, trace, tform, fill_opacity, color)

    type(layer)._drawTrace = rec
    return calls, (lambda: setattr(type(layer), "_drawTrace", orig))


DIM = (600, 400)


def _drawn_for(calls, name):
    return [(t, c, hl) for (t, c, hl) in calls if t.name == name]


# --------------------------------------------------------------------------
# Path 1: Section.editTraceAttributes (field dialog / trace list / paste)
# --------------------------------------------------------------------------
def test_incremental_render_after_editTraceAttributes_uses_new_color():
    series = _series()
    try:
        snum = list(series.sections.keys())[0]
        section = series.loadSection(snum)
        layer = _layer(series, section)
        win = list(series.window)

        square = section.contours["square"].getTraces()[0]
        assert tuple(square.color) == OLD_IS_YELLOW
        section.addSelectedTrace(square)

        # full render establishes traces_in_view (caches the OLD object)
        layer.generateTraceLayer(DIM, win, window_moved=True)
        # a table refresh clears add/remove tracking after that render
        section.clearTracking()

        # change the color (replaces the trace object with a new copy)
        section.editTraceAttributes(
            [square], name=None, color=NEW_GREEN,
            tags=None, mode=None, log_event=False,
        )
        # ...and a table refresh again empties the tracking lists before the
        # incremental render gets to consume them
        section.clearTracking()

        calls, restore = _record_draws(layer)
        try:
            # incremental render (generate_image=False -> window_moved=False)
            layer.generateTraceLayer(DIM, win, window_moved=False)
        finally:
            restore()

        drawn = _drawn_for(calls, "square")
        assert drawn, "the square trace was not drawn at all"
        # every drawn 'square' line must use the NEW color (no stale old line)
        for trace, drawn_color, _hl in drawn:
            assert drawn_color == NEW_GREEN, (
                f"stale line color {drawn_color} drawn; expected {NEW_GREEN}"
            )
        # the OLD object must not be among the drawn traces
        assert square not in [t for (t, _c, _h) in drawn], (
            "the replaced (old) trace object was still rendered"
        )
    finally:
        series.close()


def test_line_and_highlight_agree_after_color_change():
    """The exact reported symptom: highlight new, line old. Both must match."""
    series = _series()
    try:
        snum = list(series.sections.keys())[0]
        section = series.loadSection(snum)
        layer = _layer(series, section)
        win = list(series.window)

        square = section.contours["square"].getTraces()[0]
        section.addSelectedTrace(square)
        layer.generateTraceLayer(DIM, win, window_moved=True)
        section.clearTracking()

        section.editTraceAttributes(
            [square], name=None, color=NEW_GREEN,
            tags=None, mode=None, log_event=False,
        )
        section.clearTracking()

        calls, restore = _record_draws(layer)
        try:
            layer.generateTraceLayer(DIM, win, window_moved=False)
        finally:
            restore()

        drawn = _drawn_for(calls, "square")
        # the selected (highlighted) square and its line share one object/color
        highlighted = [(t, c) for (t, c, hl) in drawn if hl]
        assert highlighted, "recolored square should still be highlighted"
        for _t, c in highlighted:
            assert c == NEW_GREEN, f"highlight/line color {c} != {NEW_GREEN}"
    finally:
        series.close()


# --------------------------------------------------------------------------
# Path 2: Series.editObjectAttributes (object list, bulk/import recolor)
# --------------------------------------------------------------------------
def test_incremental_render_after_editObjectAttributes_uses_new_color():
    series = _series()
    try:
        snum = list(series.sections.keys())[0]
        section = series.loadSection(snum)
        layer = _layer(series, section)
        win = list(series.window)

        square = section.contours["square"].getTraces()[0]
        section.addSelectedTrace(square)
        layer.generateTraceLayer(DIM, win, window_moved=True)
        section.clearTracking()

        # object-list style edit routes through editTraceAttributes internally
        section.editTraceAttributes(
            section.contours["square"].getTraces(),
            name=None, color=NEW_GREEN, tags=None, mode=None,
            add_tags=True, log_event=False,
        )
        section.clearTracking()

        calls, restore = _record_draws(layer)
        try:
            layer.generateTraceLayer(DIM, win, window_moved=False)
        finally:
            restore()

        drawn = _drawn_for(calls, "square")
        assert drawn
        for _t, drawn_color, _hl in drawn:
            assert drawn_color == NEW_GREEN
    finally:
        series.close()


# --------------------------------------------------------------------------
# Sibling attribute: a name change replaces the object the same way.
# --------------------------------------------------------------------------
def test_incremental_render_after_name_change_not_stale():
    series = _series()
    try:
        snum = list(series.sections.keys())[0]
        section = series.loadSection(snum)
        layer = _layer(series, section)
        win = list(series.window)

        square = section.contours["square"].getTraces()[0]
        layer.generateTraceLayer(DIM, win, window_moved=True)
        section.clearTracking()

        section.editTraceAttributes(
            [square], name="square_renamed", color=None,
            tags=None, mode=None, log_event=False,
        )
        section.clearTracking()

        calls, restore = _record_draws(layer)
        try:
            layer.generateTraceLayer(DIM, win, window_moved=False)
        finally:
            restore()

        # the old, replaced object (name "square") must not be rendered
        assert not _drawn_for(calls, "square"), "stale renamed trace rendered"
        assert _drawn_for(calls, "square_renamed"), "renamed trace not rendered"
    finally:
        series.close()


# --------------------------------------------------------------------------
# Perf guard: a selection-only incremental refresh must NOT rebuild the full
# trace list (that would defeat the incremental optimization on large series).
# --------------------------------------------------------------------------
def test_selection_only_refresh_stays_incremental():
    series = _series()
    try:
        snum = list(series.sections.keys())[0]
        section = series.loadSection(snum)
        layer = _layer(series, section)
        win = list(series.window)

        layer.generateTraceLayer(DIM, win, window_moved=True)
        section.clearTracking()

        # only toggle a selection - no structural/attribute change
        square = section.contours["square"].getTraces()[0]
        section.addSelectedTrace(square)

        calls = {"n": 0}
        orig = type(section).tracesAsList

        def spy(self):
            calls["n"] += 1
            return orig(self)

        type(section).tracesAsList = spy
        try:
            layer.generateTraceLayer(DIM, win, window_moved=False)
        finally:
            type(section).tracesAsList = orig

        assert calls["n"] == 0, (
            "selection-only incremental refresh fell back to a full rebuild"
        )
    finally:
        series.close()

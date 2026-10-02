"""Toggling a group under `View` > `Groups` keeps unsaved edits.

`MainWindow.toggleGroupViz` reloads the field, and the reload reads each
section from its file. A trace drawn since the section was last written lived
only in memory, so the toggle threw it away, and a save after that wrote the
section without it.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "toggle_keep_obj"
GROUP = "toggle_keep_group"


def _square(series, offset=0.4):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _names(section):
    return [t.name for t in section.tracesAsList()]


@pytest.mark.parametrize("toggles", [1, 2])
def test_a_trace_drawn_before_a_group_toggle_survives(main_window, toggles,
                                                      tmp_path):
    import shutil

    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series

    series = main_window.series
    series.setProgressReporter(NullProgressReporter)
    try:
        keeper = sorted(series.data["objects"].keys())[0]
        series.object_groups.add(group=GROUP, obj=keeper)
        series.groups_visibility[GROUP] = True
        main_window.createMenuBar()

        field = main_window.field
        field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
        field.newTrace(_square(series), field.tracing_trace,
                       points_as_pix=False, reduce_points=False)
        snum = field.section.n
        assert NAME in _names(field.section)

        for _ in range(toggles):
            main_window.toggleGroupViz(GROUP)

        assert NAME in _names(main_window.field.section), "gone in memory"
        assert NAME in series.data["objects"]

        main_window.saveToJser()
        # a copy in its own folder: opening the file in place would share the
        # open window's working folder, and closing it deletes that folder
        copy = tmp_path / "reopened" / "series.jser"
        copy.parent.mkdir()
        shutil.copyfile(series.jser_fp, copy)
        reopened = Series.openJser(str(copy))
        try:
            assert NAME in _names(reopened.loadSection(snum)), (
                "gone after reopening"
            )
        finally:
            reopened.close()
    finally:
        series.setProgressReporter(None)

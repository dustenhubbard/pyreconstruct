"""A series undo keeps the object list's column choices unless columns changed.

`SeriesState.applySeriesAttributes` puts back the stored `object_columns` only
when the step changed the user columns. The check compared `object_columns`
with `user_columns`, which never match, so every series undo put the column
choices back too: show `Volume`, undo a group add, and `Volume` was hidden
again. Real Series and SeriesStates; nothing under test is patched.
"""
import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series


@pytest.fixture
def series(series_jser):
    s = Series.openJser(str(series_jser))
    s.setSettingsStore(DictSettingsStore())
    s.setProgressReporter(NullProgressReporter)
    yield s
    s.setProgressReporter(None)
    s.close()


def _shown(series, column):
    return dict(series.getOption("object_columns"))[column]


def _show(series, column):
    cols = [
        (k, True if k == column else v)
        for k, v in series.getOption("object_columns")
    ]
    series.setOption("object_columns", cols)


def test_undoing_a_group_add_keeps_a_shown_column(series):
    states = SeriesStates(series)
    obj = sorted(series.data["objects"])[0]
    assert _shown(series, "Volume") is False

    states.addState()
    series.object_groups.add(group="probe_group", obj=obj)
    _show(series, "Volume")
    states.undoState()

    assert "probe_group" not in series.object_groups.getGroupList()
    assert _shown(series, "Volume") is True
    states.undoState(redo=True)
    assert "probe_group" in series.object_groups.getGroupList()
    assert _shown(series, "Volume") is True


def test_undoing_a_user_column_add_puts_the_columns_back(series):
    states = SeriesStates(series)
    before = list(series.getOption("object_columns"))

    states.addState()
    series.addUserCol("probe_col", ["a", "b"])
    series.setOption("object_columns", before + [("probe_col", True)])
    states.undoState()

    assert "probe_col" not in series.user_columns
    assert list(series.getOption("object_columns")) == before
    states.undoState(redo=True)
    assert "probe_col" in series.user_columns
    assert ("probe_col", True) in list(series.getOption("object_columns"))

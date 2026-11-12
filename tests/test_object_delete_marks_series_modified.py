"""Deleting an object marks the series modified, so Close saves the delete.

`MainWindow.saveToJser` asks to save, and writes, only a modified series. A
delete through `Series.deleteObjects` that left the flag clear was lost on
Close: no prompt, no write, and the object was back on reopen. The Object
List marks the series modified itself, so only the API path showed it.

Each case deletes one of two kinds of object: one with traces, and one with
no traces that the series still keeps (here, a comment on a name with no
traces).
"""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

KEPT = "mod_kept_only"


def _victim(series, kind):
    """The name to delete: a traced object, or a kept name with no traces."""
    if kind == "traced":
        return sorted(series.data["objects"])[0]
    series.setAttr(KEPT, "comment", "kept with no traces")
    assert KEPT not in series.data["objects"]
    return KEPT


def _gone(series, name):
    return name not in series.data["objects"] and name not in series.obj_attrs


@pytest.mark.parametrize("kind", ["traced", "traceless"])
def test_delete_objects_marks_the_series_modified(real_series, kind):
    series = real_series
    series.setProgressReporter(NullProgressReporter)
    victim = _victim(series, kind)
    series.modified = False

    series.deleteObjects([victim])

    assert _gone(series, victim)
    assert series.modified is True
    series.setProgressReporter(None)


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["traced", "traceless"])
def test_an_api_delete_is_saved_on_close(main_window, main_window_dialogs, kind):
    window = main_window
    series = window.series
    series.setProgressReporter(NullProgressReporter)
    victim = _victim(series, kind)
    window.saveToJser()
    assert series.modified is False
    saved_path = series.jser_fp

    # no field reload: the API call alone must leave the series dirty
    series.deleteObjects([victim])

    main_window_dialogs.save_response = "yes"
    window.saveToJser(notify=True, close=True)
    assert main_window_dialogs.save_prompts == 1

    reopened = Series.openJser(saved_path, progress=NullProgressReporter)
    try:
        assert _gone(reopened, victim)
    finally:
        reopened.leave_open = False
        reopened.close()


@pytest.mark.gui
def test_an_object_list_delete_is_saved_on_close(
        main_window, main_window_dialogs, monkeypatch):
    window = main_window
    series = window.series
    series.setProgressReporter(NullProgressReporter)
    victim = _victim(series, "traced")
    window.saveToJser()
    assert series.modified is False
    saved_path = series.jser_fp

    field = window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: [victim])
    field.deleteObjects()
    assert series.modified is True

    main_window_dialogs.save_response = "yes"
    window.saveToJser(notify=True, close=True)
    assert main_window_dialogs.save_prompts == 1

    reopened = Series.openJser(saved_path, progress=NullProgressReporter)
    try:
        assert _gone(reopened, victim)
    finally:
        reopened.leave_open = False
        reopened.close()

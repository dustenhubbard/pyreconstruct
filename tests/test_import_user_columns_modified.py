"""User columns imported from the Object List must be saved."""

import pytest

from PyReconstruct.modules.datatypes import Series

pytestmark = pytest.mark.gui


@pytest.fixture
def object_list(main_window):
    manager = main_window.field.table_manager
    manager.newTable("object")
    return manager.tables["object"][-1]


@pytest.fixture
def columns_file(tmp_path):
    path = tmp_path / "columns.txt"
    path.write_text("CloseAudit: draft, checked\n", encoding="utf-8")
    return str(path)


def test_import_marks_series_modified_and_saves(
    main_window, main_window_dialogs, object_list, columns_file, series_jser,
):
    assert main_window.series.modified is False
    main_window_dialogs.file_responses.append(columns_file)

    object_list.importUserColText()

    assert main_window.series.user_columns["CloseAudit"] == ["draft", "checked"]
    assert "CloseAudit" in object_list.getHeaders()
    assert main_window.series.modified is True
    main_window.saveToJser()
    assert main_window.series.modified is False
    assert main_window.close()

    reopened = Series.openJser(str(series_jser))
    try:
        assert reopened.user_columns["CloseAudit"] == ["draft", "checked"]
    finally:
        reopened.close()


def test_close_after_import_prompts_and_saves(
    main_window, main_window_dialogs, object_list, columns_file, series_jser,
):
    assert main_window.series.modified is False
    main_window_dialogs.file_responses.append(columns_file)
    main_window_dialogs.save_response = "yes"

    object_list.importUserColText()
    assert main_window.close()
    assert main_window_dialogs.save_prompts == 1

    reopened = Series.openJser(str(series_jser))
    try:
        assert reopened.user_columns["CloseAudit"] == ["draft", "checked"]
    finally:
        reopened.close()


def test_canceling_import_keeps_series_clean(main_window, object_list):
    assert main_window.series.modified is False
    before = main_window.series.user_columns.copy()

    object_list.importUserColText()

    assert main_window.series.user_columns == before
    assert main_window.series.modified is False

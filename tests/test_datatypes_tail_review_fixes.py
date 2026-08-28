"""The datatypes-and-lists tail of the review findings (2026-08-28).

The headline is the rename corruption: section files are named
"<series name>.<section number>", and a plain str.replace on the whole
filename rewrote the numeric suffix whenever the series name's text occurred
in it. A series literally named "5" lost a section outright on Save-As.
"""


import pytest

from PyReconstruct.modules.datatypes.series import renamedSeriesFile

pytestmark = pytest.mark.gui


# --- the rename itself, as a pure function --------------------------------------

@pytest.mark.parametrize("filename, old, new, expected", [
    ("5.55", "5", "6", "6.55"),          # the suffix is a SECTION, not a name
    ("5.66", "5", "6", "6.66"),          # no collision with the case above
    ("5.ser", "5", "6", "6.ser"),        # the index file follows
    ("55", "5", "6", "55"),              # a timer file: no dot, untouched
    ("existing_log.csv", "5", "6", "existing_log.csv"),
    ("my.series.12", "my.series", "their.series", "their.series.12"),
    ("other.12", "5", "6", "other.12"),  # a different series' file
])
def test_only_the_name_prefix_is_renamed(filename, old, new, expected):
    assert renamedSeriesFile(filename, old, new) == expected


def test_a_numeric_series_name_survives_a_rename(real_series):
    """The in-memory index after rename(): every section keeps its number."""
    real_series.name = "5"
    real_series.sections = {55: "5.55", 66: "5.66"}

    real_series.rename("6")

    assert real_series.sections == {55: "6.55", 66: "6.66"}


# --- the clean-up appliers only touch named sections -----------------------------

def test_repair_and_delete_load_only_the_named_sections(real_series, monkeypatch):
    loaded = []
    real_load = type(real_series).loadSection

    def counting_load(self, snum):
        loaded.append(snum)
        return real_load(self, snum)

    monkeypatch.setattr(type(real_series), "loadSection", counting_load)

    target = sorted(real_series.sections)[3]
    record = {
        "name": "no_such_object", "section": target, "index": 0, "points": 4,
        "location": (0.0, 0.0), "reason": "test",
        "match": {"color": (1, 2, 3), "points": []}, "repairable": True,
    }

    loaded.clear()
    real_series.deleteMalformedTraces([record])
    assert set(loaded) == {target}, (
        f"a one-record delete loaded sections {sorted(set(loaded))}"
    )

    loaded.clear()
    real_series.repairSelfCrossingTraces([record])
    assert set(loaded) == {target}


# --- the calgrid lock checkbox ----------------------------------------------------

def test_lock_checkbox_survives_the_calgrid_suffix(main_window, qapp):
    """int('0 (calgrid)') raised and desynced the checkbox from the lock."""
    window = main_window
    snum = sorted(window.series.sections)[0]
    window.series.data["sections"][snum]["calgrid"] = True

    window.field.table_manager.newTable("section")
    qapp.processEvents()
    table = window.field.table_manager.tables["section"][-1]

    row = None
    for r in range(table.table.rowCount()):
        if table.table.item(r, 0).text().startswith(str(snum)):
            row = r
            break
    assert row is not None
    assert "(calgrid)" in table.table.item(row, 0).text(), (
        "the fixture row never grew the calgrid suffix this test is about"
    )

    from PySide6.QtCore import Qt

    locked_col = next(
        c for c in range(table.table.columnCount())
        if table.table.horizontalHeaderItem(c).text() == "Locked"
    )
    item = table.table.item(row, locked_col)
    was_locked = item.checkState() == Qt.CheckState.Checked
    item.setCheckState(
        Qt.CheckState.Unchecked if was_locked else Qt.CheckState.Checked
    )
    qapp.processEvents()

    # the REAL lock followed the checkbox; before the fix this raised and
    # only the checkbox changed
    section = window.series.loadSection(snum)
    assert section.align_locked != was_locked


# --- closed lists and history views are destroyed, not hidden ----------------------

def test_a_closed_list_is_destroyed(main_window, qapp):
    from shiboken6 import isValid

    main_window.field.table_manager.newTable("object")
    qapp.processEvents()
    table = main_window.field.table_manager.tables["object"][-1]

    table.close()
    for _ in range(5):
        qapp.processEvents()

    assert not isValid(table), "a closed list survived as a hidden dock"


def test_a_closed_history_view_is_destroyed(main_window, qapp):
    from shiboken6 import isValid

    from PyReconstruct.modules.gui.table import HistoryTableWidget

    widget = HistoryTableWidget(
        main_window.series.getFullHistory(), main_window
    )
    widget.close()
    for _ in range(5):
        qapp.processEvents()

    assert not isValid(widget), "a closed history view survived hidden"

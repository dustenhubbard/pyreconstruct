"""FlagTableWidget.updateData with the Section column hidden.

The flag list is the one data list whose key column is user-hideable. The
other four pin their key as a ``static_columns`` prefix the columns dialog
cannot touch (``["Name"]`` for trace/ztrace, ``["Section"]`` for the section
list; the object list is model-backed and keys off ``model().rowOf(name)``).
``flag.py`` declares no ``static_columns``, so unchecking Section -- offered
by both the series options dialog (``all_options.py``, ``flag_columns``) and
the list's own "Set columns..." -- makes column 0 the Color swatch, whose
cell text is a single space.

``updateData`` used to locate a section's rows with
``CopyTableWidget.getRowIndex(str(section.n))``, a text search over column 0.
With Section hidden the section number is in NO column, so the search fell
through to ``(rowCount(), False)`` every time. Measured severity on the
unfixed code (no exception anywhere): stale rows were never removed -- a
just-resolved flag stayed listed -- and the refreshed rows were appended at
the bottom, so every ``updateData`` for a section grew the table by that
section's row count (6 -> 8 -> 10 across two updates in the probe), duplicates
accumulating without bound and section sort order lost.

The fix keys the lookup off ``displayed_flags`` (kept parallel to the table
rows by ``setRow``/``insertRow``/``removeRow`` regardless of visible columns)
via ``FlagTableWidget.getSectionRowIndex``. These tests hide the column
through the widget's real "Set columns..." path -- real ``TableColumnsDialog``,
real checkbox toggle driving ``checkColumn`` -- with only the modal exec loop
scripted, since offscreen Qt has no user to dismiss one.
"""

import pytest

pytestmark = pytest.mark.gui


class RecreatingStubManager:
    """The manager surface these tests need, with a REAL recreateTable.

    Unlike the no-op stubs elsewhere in the suite, ``recreateTable`` here
    mirrors ``TableManager.recreateTable`` (backend/table/manager.py): for a
    non-trace table it calls ``createTable()`` with no arguments. The
    "Set columns..." path ends in exactly that call, and the bug under test
    only exists in the rebuilt, Section-less table.
    """

    def __init__(self):
        self.series_states = {}
        self.tables = {
            "section": [], "trace": [], "ztrace": [], "flag": [], "object": [],
        }

    def refresh(self):
        pass

    def recreateTable(self, table=None):
        if table is not None:
            table.createTable()

    def recreateTables(self, refresh_data=False):
        pass


@pytest.fixture
def flag_table(qapp, stub_mainwindow, gui_dialogs):
    """A real FlagTableWidget over the writable fixture series, six flags.

    Settings are redirected into a ``DictSettingsStore`` before the widget is
    built: the widget's option reads write defaults back on miss, and nothing
    here may touch the real QSettings domain. ``flag_columns`` itself is a
    series-internal option, stored in the per-test jser copy.
    """
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes import Flag
    from PyReconstruct.modules.gui.table.flag import FlagTableWidget

    series = stub_mainwindow.series
    series.setSettingsStore(DictSettingsStore())

    for i, snum in enumerate((3, 3, 4, 4, 5, 5)):
        section = series.loadSection(snum)
        section.addFlag(Flag(f"flag{i:02d}", i, i, snum, (255, 0, 0)))
        section.save()

    widget = FlagTableWidget(series, stub_mainwindow, RecreatingStubManager())
    yield widget
    widget.deleteLater()
    series.setSettingsStore(None)


def hide_section_column(widget, monkeypatch):
    """Uncheck Section through the widget's own "Set columns..." slot."""
    from PySide6.QtWidgets import QCheckBox

    import PyReconstruct.modules.gui.dialog.table_columns as table_columns

    def scripted_exec(self):
        for checkbox in self.findChildren(QCheckBox):
            if checkbox.text() == "Section":
                # fires stateChanged -> checkColumn, the real dialog wiring
                checkbox.setChecked(False)
        return self.columns, True

    monkeypatch.setattr(table_columns.TableColumnsDialog, "exec", scripted_exec)
    widget.setColumns()


def live_rows(widget):
    """(name, snum) per table row, from the parallel displayed_flags list."""
    return [
        (widget.displayed_flags[r].name, widget.displayed_flags[r].snum)
        for r in range(widget.table.rowCount())
    ]


def test_hiding_section_leaves_no_column_carrying_the_section_number(flag_table, monkeypatch):
    """Pin the premise: with Section unchecked there is nothing for a
    column-0 (or any-column) text search to find."""
    hide_section_column(flag_table, monkeypatch)

    headers = flag_table.horizontal_headers
    assert "Section" not in headers
    assert headers[0] == "Color"
    # column 0 is the color swatch: a single space in every row
    texts = {
        flag_table.table.item(r, 0).text()
        for r in range(flag_table.table.rowCount())
    }
    assert texts == {" "}


def test_get_section_row_index_finds_rows_with_section_hidden(flag_table, monkeypatch):
    hide_section_column(flag_table, monkeypatch)

    # sections 3/4/5 hold rows 0-1 / 2-3 / 4-5
    assert flag_table.getSectionRowIndex(3) == (0, True)
    assert flag_table.getSectionRowIndex(4) == (2, True)
    assert flag_table.getSectionRowIndex(5) == (4, True)
    # a section with no flags: insert position, not found
    assert flag_table.getSectionRowIndex(0) == (0, False)
    assert flag_table.getSectionRowIndex(99) == (6, False)


def test_update_with_section_hidden_replaces_rows_in_place(flag_table, monkeypatch):
    """The measured failure: before the fix this update left the table at 8
    rows -- the resolved flag02 still listed, flag03 duplicated, the fresh
    section-4 rows appended after section 5."""
    hide_section_column(flag_table, monkeypatch)

    series = flag_table.series
    section4 = series.loadSection(4)
    section4.flags[0].resolve(series.user, True)  # drops out: resolved hidden
    from PyReconstruct.modules.datatypes import Flag
    section4.addFlag(Flag("newflag", 9, 9, 4, (0, 255, 0)))
    section4.save()

    flag_table.updateData(section4)

    assert live_rows(flag_table) == [
        ("flag00", 3), ("flag01", 3),
        ("flag03", 4), ("newflag", 4),
        ("flag04", 5), ("flag05", 5),
    ]


def test_repeated_updates_do_not_grow_the_table(flag_table, monkeypatch):
    """Before the fix every updateData appended the section's rows again
    (6 -> 8 -> 10 rows measured); it must be idempotent."""
    hide_section_column(flag_table, monkeypatch)

    section4 = flag_table.series.loadSection(4)
    flag_table.updateData(section4)
    once = live_rows(flag_table)
    flag_table.updateData(section4)

    assert live_rows(flag_table) == once
    assert flag_table.table.rowCount() == 6


def test_new_section_rows_insert_in_section_order(flag_table, monkeypatch):
    """Insert position must come from the flags, not from column-0 text:
    a section gaining its first rows lands between its neighbours."""
    from PyReconstruct.modules.datatypes import Flag

    hide_section_column(flag_table, monkeypatch)

    series = flag_table.series
    section4 = series.loadSection(4)
    section4.flags.clear()
    section4.save()
    flag_table.updateData(section4)
    assert live_rows(flag_table) == [
        ("flag00", 3), ("flag01", 3), ("flag04", 5), ("flag05", 5),
    ]

    section4.addFlag(Flag("reborn", 1, 1, 4, (0, 0, 255)))
    section4.save()
    flag_table.updateData(section4)
    assert live_rows(flag_table) == [
        ("flag00", 3), ("flag01", 3), ("reborn", 4),
        ("flag04", 5), ("flag05", 5),
    ]


def test_update_with_default_columns_still_replaces_rows(flag_table):
    """Control: the rewritten lookup must not regress the shipped default
    layout, where Section is visible and the old text search happened to
    work."""
    from PyReconstruct.modules.datatypes import Flag

    series = flag_table.series
    section4 = series.loadSection(4)
    section4.addFlag(Flag("extra", 5, 5, 4, (255, 255, 0)))
    section4.save()

    flag_table.updateData(section4)

    assert flag_table.horizontal_headers[0] == "Section"
    # flags within a section render in Flag.__lt__ order, i.e. by name
    assert live_rows(flag_table) == [
        ("flag00", 3), ("flag01", 3),
        ("extra", 4), ("flag02", 4), ("flag03", 4),
        ("flag04", 5), ("flag05", 5),
    ]

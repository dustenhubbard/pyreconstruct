"""The table manager reads the Section and Series tracking and never clears
it: the undo history does (test_section_undo_seam). Kept apart from those
tests because the table manager imports Qt and they must not."""

from PyReconstruct.modules.backend.table.manager import TableManager

from test_section_undo_seam import NAME, ZNAME, draw
from test_section_undo_seam import bench  # noqa: F401  (fixture)


class _Tables:
    """TableManager's update methods on the attributes they read, so they
    run without a window."""

    updateObjects = TableManager.updateObjects
    updateSections = TableManager.updateSections
    updateZtraces = TableManager.updateZtraces
    updateFlags = TableManager.updateFlags
    updateAll = TableManager.updateAll

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.tables = {k: [] for k in ("object", "trace", "ztrace", "flag", "section")}
        self.mainwindow = None

    def _markViewerStale(self, *args, **kwargs):
        pass


def test_the_table_manager_reads_tracking_and_never_clears_it(bench):  # noqa: F811
    series, section, states = bench
    draw(section)
    series.modified_ztraces.add(ZNAME)
    tables = _Tables(series, section)

    tables.updateObjects()
    tables.updateZtraces()
    tables.updateAll()

    assert set(section.getAllModifiedNames()) == {NAME}
    assert series.modified_ztraces == {ZNAME}

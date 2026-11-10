"""Known geometry keeps its quantities and row identity through CSV export."""

import csv
import io

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, Trace


@pytest.fixture
def measured_series(tmp_path):
    series = Series.new(
        [str(tmp_path / f"image{i}.tif") for i in range(3)],
        "measurements", 1, 0.5,
    )
    series.setSettingsStore(DictSettingsStore())
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    try:
        # A 4-by-3 rectangle, a hidden negative unit square, and an open
        # 3-4 path. The empty middle section must not contribute to this object.
        for snum, section in series.enumerateSections(show_progress=False):
            section.thickness = (0.5, 0.25, 0.75)[snum]
            if snum == 0:
                outer = Trace("mixed", (255, 0, 0))
                outer.points = [(0, 0), (4, 0), (4, 3), (0, 3)]
                outer.tags = {"outer"}
                hole = Trace("mixed", (0, 0, 255))
                hole.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
                hole.negative = hole.hidden = True
                hole.tags = {"hole"}
                traces = [outer, hole]
            elif snum == 1:
                line = Trace("a-open", (0, 255, 0), closed=False)
                line.points = [(0, 0), (3, 4)]
                square = Trace("z-closed", (255, 0, 0))
                square.points = [(0, 0), (2, 0), (2, 2), (0, 2)]
                traces = [line, square]
            else:
                path = Trace("mixed", (0, 255, 0), closed=False)
                path.points = [(0, 0), (3, 0), (3, 4)]
                path.tags = {"path"}
                traces = [path]
            for trace in traces:
                section.addTrace(trace, log_event=False)
            section.save()
        series.code = "MEASURE"
        yield series
    finally:
        series.leave_open = False
        series.close()


def object_rows(text):
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter="|"))


def trace_rows(text):
    return list(csv.DictReader(io.StringIO(text, newline="")))


@pytest.mark.parametrize(
    "name,start,end,count,flat_area,volume,configuration",
    [
        ("mixed", 0, 2, 3, 16.25, 5.5, "mixed"),
        ("a-open", 1, 1, 1, 1.25, 0, "open"),
        ("z-closed", 1, 1, 1, 4, 1, "closed"),
    ],
)
def test_object_quantities_use_signed_area_and_each_sections_thickness(
    measured_series, name, start, end, count, flat_area, volume, configuration,
):
    # mixed: flat area = 12 - 1 + 7 * .75; volume = (12 - 1) * .5.
    obj = measured_series.objects[name]
    assert (obj.start, obj.end, obj.count) == (start, end, count)
    assert obj.flat_area == pytest.approx(flat_area)
    assert obj.volume == pytest.approx(volume)
    assert measured_series.data.getConfiguration(name) == configuration

    rows = object_rows(measured_series.objects.exportCSV())
    assert [row["Name"] for row in rows] == ["a-open", "mixed", "z-closed"]
    row = next(row for row in rows if row["Name"] == name)
    assert (int(row["Start"]), int(row["End"]), int(row["Count"])) == (start, end, count)
    assert float(row["Flat_Area"]) == pytest.approx(flat_area)
    assert float(row["Volume"]) == pytest.approx(volume)


def test_unknown_objects_do_not_report_measured_zero(measured_series):
    data = measured_series.data
    for getter, expected in (
        (data.getStart, 0), (data.getEnd, 2), (data.getCount, 3),
        (data.getFlatArea, 16.25), (data.getVolume, 5.5),
        (data.getConfiguration, "mixed"),
    ):
        assert getter("mixed") == expected
        assert getter("missing") is None
    assert data.getAvgRadius("a-open") == pytest.approx(2.5)
    assert data.getAvgRadius("missing") is None
    assert data.getTags("mixed") == {"outer", "hole", "path"}
    assert data.getTags("missing") == set()
    assert data.getColorCounts("mixed") == {
        (255, 0, 0): 1, (0, 0, 255): 1, (0, 255, 0): 1,
    }
    assert data.getColorCounts("missing") == {}
    assert measured_series.objects["missing"] is None


def test_trace_export_keeps_signed_measurements_with_their_rows(measured_series):
    rows = trace_rows(measured_series.data.exportTracesCSV())
    assert [(r["Name"], r["Section"], r["Index"]) for r in rows] == [
        ("a-open", "1", "0"), ("mixed", "0", "0"),
        ("mixed", "0", "1"), ("mixed", "2", "0"), ("z-closed", "1", "0"),
    ]
    outer, hole, path = rows[1:4]
    assert [float(r["Area"]) for r in (outer, hole, path)] == [12, -1, 0]
    assert [float(r["Length"]) for r in (outer, hole, path)] == [14, 4, 7]
    assert (outer["Hidden"], hole["Hidden"], path["Closed"]) == ("no", "yes", "no")
    assert (float(outer["Centroid-x"]), float(outer["Centroid-y"])) == (2, 1.5)
    assert (float(outer["Radius"]), float(outer["Feret-Max"]), float(outer["Feret-Min"])) == (2.5, 5, 3)
    assert (float(hole["Feret-Max"]), float(hole["Feret-Min"])) == pytest.approx((1.4142136, 1))
    assert (path["Feret-Max"], path["Feret-Min"]) == ("0", "0")
    assert [r["Tags"] for r in (outer, hole, path)] == ["outer", "hole", "path"]


@pytest.mark.parametrize(
    "curation,expected",
    [
        (None, ("", "", "")),
        ((True, "alice", "2026-11-02"), ("Curated", "alice", "2026-11-02")),
        ((False, "bob", "2026-11-01"), ("Needs Curation", "bob", "2026-11-01")),
    ],
)
def test_object_export_keeps_curation_and_metadata_with_quantities(
    measured_series, curation, expected,
):
    series = measured_series
    series.setAttr("mixed", "curation", curation)
    series.setAttr("mixed", "last_user", "alice")
    series.setAttr("mixed", "comment", "checked|again")
    series.object_groups.add("dendrites", "mixed")
    row = object_rows(series.objects.exportCSV())[1]
    assert (row["Curation_Status"], row["Curation_User"], row["Curation_Date"]) == expected
    assert row["Name"] == "mixed"
    assert row["Series"] == "MEASURE"
    assert row["Groups"] == "dendrites"
    assert set(row["Trace_Tags"].split(":")) == {"outer", "hole", "path"}
    assert row["Last_User"] == "alice"
    assert row["Alignment"] == "default"
    assert row["Comment"] == "checked_again"
    assert float(row["Volume"]) == 5.5


@pytest.mark.parametrize("tag", ["review,again", '"quoted"', "first\nsecond", "first\rsecond"])
def test_trace_export_quotes_tags_without_shifting_quantities(measured_series, tmp_path, tag):
    section = measured_series.loadSection(0)
    section.editTraceAttributes(
        [section.contours["mixed"][0]], None, None, {tag}, None, log_event=False,
    )
    section.save()
    text = measured_series.data.exportTracesCSV()
    out = tmp_path / "traces.csv"
    measured_series.data.exportTracesCSV(str(out))
    for rows in (trace_rows(text), trace_rows(out.read_bytes().decode())):
        assert len(rows) == 5
        row = next(r for r in rows if r["Name"] == "mixed" and r["Section"] == "0" and r["Hidden"] == "no")
        assert None not in row
        assert (row["Name"], row["Tags"]) == ("mixed", tag)
        assert (float(row["Area"]), float(row["Length"])) == (12, 14)


@pytest.mark.parametrize("name", ['"quoted"', "axon|branch"])
def test_exports_preserve_allowed_object_names(measured_series, name):
    series = measured_series
    series.editObjectAttributes(["mixed"], name=name)
    rows = trace_rows(series.data.exportTracesCSV())
    matching = [row for row in rows if row["Name"] == name]
    assert len(matching) == 3
    assert [float(row["Area"]) for row in matching] == [12, -1, 0]
    rows = object_rows(series.objects.exportCSV())
    assert len(rows) == 3
    row = next(row for row in rows if row["Name"] == name)
    assert None not in row
    assert float(row["Volume"]) == 5.5


@pytest.mark.parametrize(
    "field,value",
    [("comment", 'checked\n"again"'), ("comment", "checked\ragain"),
     ("last_user", "alice|bob")],
)
def test_object_export_quotes_metadata_without_splitting_rows(
    measured_series, tmp_path, field, value,
):
    series = measured_series
    series.setAttr("mixed", field, value)
    series.object_groups.add("dendrites|reviewed", "mixed")
    text = series.objects.exportCSV()
    out = tmp_path / "objects.csv"
    series.exportObjectsCSV(out)
    column = {"comment": "Comment", "last_user": "Last_User"}[field]
    for rows in (object_rows(text), object_rows(out.read_bytes().decode())):
        assert len(rows) == 3
        row = rows[1]
        assert None not in row
        assert row["Name"] == "mixed"
        assert row[column] == value
        assert row["Groups"] == "dendrites|reviewed"
        assert float(row["Volume"]) == 5.5

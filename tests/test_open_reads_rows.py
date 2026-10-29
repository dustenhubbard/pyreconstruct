"""A series open reads each section's rows without building a `Section`
(section_rows.py). It must leave the same series data, the same trace-id
issuer and the same object ids as the open that built every `Section`, and a
later section load must get the same trace ids.

The old open is the same code with `readSectionRows` answering None for every
section, which sends each one through `Series.loadSection` and
`SeriesData.updateSection`, as before.
"""
import json
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, section_rows
from PyReconstruct.modules.datatypes.series_data import SeriesData
from PyReconstruct.modules.datatypes.trace_id import encodeTraceID

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = {
    "parity": ROOT / "tests" / "fixtures" / "parity_series.jser",
    "shapes1": ROOT / "dev" / "assets" / "checker" / "files" / "shapes1.jser",
    "shapes2": ROOT / "dev" / "assets" / "checker" / "files" / "shapes2.jser",
}


def _old_open(monkeypatch):
    """Build every section as a `Section`, as the open did before."""
    monkeypatch.setattr(section_rows, "readSectionRows", lambda n, series: None)


def _row(x, y, color=(10, 20, 30), closed=True, negative=False, hidden=False, tags=()):
    return [list(x), list(y), list(color), closed, negative, hidden, ["none", "none"], list(tags)]


SQUARE = ([0.0, 1.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0])


def _keyed(trace_id, x, y):
    return {"x": list(x), "y": list(y), "color": [1, 2, 3], "closed": True,
            "negative": False, "hidden": False, "fill_mode": ["none", "none"],
            "tags": [], "id": trace_id}


def _section(n, contours, tforms=None):
    return {
        "src": f"odd.{n}.png", "mag": 0.00254, "thickness": 0.05, "align_locked": False,
        "tforms": tforms or {"default": [1, 0, 0, 0, 1, 0]},
        "contours": contours, "flags": [],
    }


def _odd_series(path):
    """A series with every row the store or `Trace.fromList` reads in its own way."""
    clash = encodeTraceID(0x1234_5678_9ABC)
    sections = [
        _section(0, {}),
        _section(1, {
            "plain": [_row(*SQUARE), _row([2, 3, 3], [2, 2, 3], tags=["t", "u"])],
            "flags": [_row(*SQUARE, closed=1, negative=1, hidden=0)],
            "two": [_row([0, 1], [0, 1], closed=True)],
        }, tforms={"default": [1, 0, 0.5, 0, 1, -2], "other": [2, 0, 0, 0, 2, 0]}),
        ## one section per row the store reads in its own way, so each is
        ## the only reason its section is built as a Section
        ## colors that are not ints: the store keeps uint8 (an int over 255
        ## wraps on numpy 1 and is refused on numpy 2, by both opens)
        _section(2, {"wide": [_row(*SQUARE, color=(255.9, 0, 0))]}),
        _section(3, {"float": [_row(*SQUARE, color=(1.5, True, 2))]}),
        ## a string axis, unequal lengths, one point
        _section(4, {"string axis": [_row("123", "456")]}),
        _section(5, {"unequal": [_row([0, 1, 2, 3], [0, 1, 2])]}),
        _section(6, {"single": [_row([1], [1]), _row(*SQUARE)]}),
        ## an old 9-field row (updateJSON drops the last field), a name
        ## updateJSON normalizes, a fill mode it replaces
        _section(7, {
            "nine": [[*_row(*SQUARE), "extra"]],
            "  spaced, name ": [_row(*SQUARE)],
            "mode": [[*_row(*SQUARE)[:6], "solid", []]],
        }),
        _section(8, {
            "keyed": [_keyed(clash, *SQUARE), _keyed("not-an-id", *SQUARE)],
            "plain": [_row(*SQUARE), _row(*SQUARE)],
        }),
        ## a second claim on section 8's id, from another section
        _section(9, {"rival": [_keyed(clash, [5, 6, 6], [5, 5, 6])]}),
    ]
    path.write_text(json.dumps({"series": {}, "sections": sections, "log": ""}))
    return path


def _open(path):
    series = Series.openJser(str(path))
    series.setSettingsStore(DictSettingsStore())
    return series


def _issuer(series):
    return {k: v for k, v in vars(series.trace_id_issuer).items() if k != "_bits_source"}


def _object_ids(series):
    ids = series.data.object_ids
    return (repr(ids._counter), ids.placed, ids.name_of, ids._live, ids.version)


def _state(series):
    """The series data, field by field and in order, with its id records."""
    data = series.data
    objects = [
        (name, [
            (snum, [
                (td.index, td.closed, td.hidden, td.negative, sorted(td.tags), td.color,
                 td.length, td.area, td.centroid, td.radius, td._tform.getList(), td._feret)
                for td in traces
            ])
            for snum, traces in obj.traces.items()
        ])
        for name, obj in data.objects.items()
    ]
    sections = [
        (snum, d["thickness"], d["calgrid"], d["locked"], d["bc_profiles"], d["src"], d["mag"],
         [f.getList() for f in d["flags"]],
         {a: t.getList() for a, t in d["tforms"].items()}, type(d["tforms"]))
        for snum, d in data["sections"].items()
    ]
    alignments = {name: series.getAttr(name, "alignment") for name in data.objects}
    return repr((objects, sections, alignments)), _issuer(series), _object_ids(series)


def _later_loads(series):
    """Every section's trace ids from a later load, and the issuer after."""
    ids = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        store = section._columns
        ids[snum] = (section.trace_ids_trusted, [
            (name, [store.getID(row) for row in store.rowsForContour(name)])
            for name in section.contours
        ])
    return ids, _issuer(series)


def _both_opens(source, tmp_path, monkeypatch):
    opened = {}
    for arm in ("old", "new"):
        folder = tmp_path / arm
        folder.mkdir()
        shutil.copy(source, folder / "series.jser")
        with monkeypatch.context() as m:
            if arm == "old":
                _old_open(m)
            opened[arm] = _open(folder / "series.jser")
    return opened["old"], opened["new"]


@pytest.fixture(params=["class", *FIXTURES, "odd"])
def source(request, series_jser, tmp_path):
    if request.param == "class":
        return series_jser
    if request.param == "odd":
        return _odd_series(tmp_path / "odd.jser")
    return FIXTURES[request.param]


def test_first_open_matches_the_section_open(source, tmp_path, monkeypatch):
    old, new = _both_opens(source, tmp_path, monkeypatch)
    try:
        assert old.data.objects, "the fixture has no trace data to compare"
        assert _state(new) == _state(old)
        assert _later_loads(new) == _later_loads(old)
    finally:
        old.close()
        new.close()


def test_resume_matches_the_section_open(source, tmp_path, monkeypatch):
    ## the working folder a first open left, opened again as a resume does
    first = _open(_copy(source, tmp_path))
    fp, sections = first.filepath, dict(first.sections)
    try:
        with monkeypatch.context() as m:
            _old_open(m)
            old = Series(fp, sections)
        new = Series(fp, sections)
        assert _state(new) == _state(old)
        assert _later_loads(new) == _later_loads(old)
    finally:
        first.close()


def _copy(source, tmp_path):
    folder = tmp_path / "copy"
    folder.mkdir()
    shutil.copy(source, folder / "series.jser")
    return folder / "series.jser"


def test_the_odd_series_takes_both_paths(tmp_path, monkeypatch):
    """The plain sections are read as rows, the rest as Sections."""
    path = _odd_series(tmp_path / "odd.jser")
    read = {}
    real = section_rows.readSectionRows

    def recording(n, series):
        read[n] = real(n, series)
        return read[n]

    monkeypatch.setattr(section_rows, "readSectionRows", recording)
    series = _open(path)
    series.close()
    ## the unpack's working copy splits a string axis into a list, and
    ## updateJSON drops a one-point row, so sections 4 and 6 are plain
    assert [n for n in sorted(read) if read[n] is None] == [2, 3, 5]
    assert _odd_issuer_sanity(path, tmp_path)


def _odd_issuer_sanity(path, tmp_path):
    """The planted clash and the malformed id are recorded, as the old open records them."""
    series = _open(_copy(path, tmp_path))
    try:
        issuer = series.trace_id_issuer
        return len(issuer.collisions) == 1 and len(issuer.malformed) == 1
    finally:
        series.close()


def test_own_alignment_order_and_clearing_match(series_jser, monkeypatch):
    """An object with its own alignment is measured with it, created in
    contour order, and an alignment no section has is cleared."""
    series = _open(series_jser)
    try:
        section = series.loadSection(sorted(series.sections)[0])
        other = next(a for a in section.tforms if a != series.alignment)
        names = sorted(series.data.objects)

        def plant():
            for name in names[::3]:
                series.setAttr(name, "alignment", other)
            series.setAttr(names[1], "alignment", "no such alignment")

        plant()
        series.data.refresh(from_rows=True)
        new = _state(series)[0]
        assert series.getAttr(names[1], "alignment") is None
        plant()
        with monkeypatch.context() as m:
            ## the store's rows one at a time, in contour order
            m.setattr(SeriesData, "_storeRows", lambda self, store, section, names: None)
            series.data.refresh()
        assert new == _state(series)[0]
    finally:
        series.close()


def test_objects_are_created_in_contour_order(tmp_path, monkeypatch):
    """Section 1 measures "plain" with its own alignment after "flags" and
    "two"; the objects still come in contour order, as one trace at a time
    gives them, and section 2 (which lacks the alignment) clears it."""
    series = _open(_odd_series(tmp_path / "odd.jser"))
    try:
        series.setAttr("plain", "alignment", "other")
        series.data.refresh(from_rows=True)
        new = _state(series)
        assert list(series.data.objects)[:3] == ["flags", "plain", "two"]
        assert series.getAttr("plain", "alignment") is None
        series.setAttr("plain", "alignment", "other")
        with monkeypatch.context() as m:
            m.setattr(SeriesData, "_storeRows", lambda self, store, section, names: None)
            _old_open(m)
            series.data.refresh()
        assert new == _state(series)
    finally:
        series.close()

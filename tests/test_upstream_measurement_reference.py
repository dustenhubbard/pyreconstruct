"""Trace measurements and trace tools against upstream's, on real traces.

`tests/upstream_reference/class_series_35c87fa9.json` holds what
SynapseWeb/PyReconstruct at 35c87fa9 measured on every trace of
class_series.jser, plus a few named synthetic inputs the series lacks
(`tests/upstream_reference/generate.py` made it; these tests only read it).
The fork's own equivalence tests compute their reference with fork code, so a
change that moves both together passes them; it does not pass these.

Each measure must match upstream's raw value within `oracle.TOLERANCES`
(absolute, rel=0), unless the reference records a fork expectation for it,
with one of three reasons:

* centroid-rounding-order: upstream rounds then maps, the fork maps then
  rounds; bounded by `oracle.centroidBound`;
* minimum-width: the fork reports the true minimum width (c9f27ab1), never
  more than upstream's antipodal pair distance;
* far-from-origin-precision: the fork keeps a small trace far from the origin
  precise (97713536); synthetic only.

Every fork value, recorded difference or not, is also checked against the
oracle, which measures from the points by exact arithmetic.
"""

import copy
import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.calc import mergeTraces, reducePoints
from PyReconstruct.modules.calc.grid import mergeTracesInField
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.datatypes.section_rows import measureGeometries
from PyReconstruct.modules.datatypes.series_data import TraceData
from PyReconstruct.modules.datatypes.transform import Transform

from conftest import SERIES_FIXTURE
from upstream_reference import oracle

REFERENCE_PATH = Path(__file__).resolve().parent / "upstream_reference" / "class_series_35c87fa9.json"
UPSTREAM_SHA = "35c87fa9f444d2ef0be486b7133f0c177e4f9884"
PATHS = ("trace_data", "batch", "series_data")
CSV_COLUMNS = {"Length": "length", "Area": "area", "Radius": "radius", "Centroid-x": "cx",
               "Centroid-y": "cy", "Feret-Max": "feret_max", "Feret-Min": "feret_min"}


def _key(ident) -> tuple:
    return ident["section"], ident["name"], ident["index"]


@pytest.fixture(scope="module")
def reference():
    with open(REFERENCE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def series(tmp_path_factory):
    destination = tmp_path_factory.mktemp("upstream_reference") / "series.jser"
    shutil.copy(SERIES_FIXTURE, destination)
    opened = Series.openJser(str(destination))
    opened.setSettingsStore(DictSettingsStore())
    opened.setProgressReporter(NullProgressReporter)
    opened.setNotifier(NullNotifier())
    yield opened
    opened.leave_open = False
    opened.close()


@pytest.fixture(scope="module")
def sections(series):
    return {n: series.loadSection(n) for n in sorted(series.sections)}


def _feret(data, section, name) -> tuple:
    diameters = data.getFeret(section, name)
    assert diameters is not None
    return diameters


def _values(data, feret) -> dict:
    cx, cy = data.getCentroid()
    return {"length": data.getLength(), "area": data.getArea(), "radius": data.getRadius(),
            "cx": cx, "cy": cy, "feret_min": feret[0], "feret_max": feret[1]}


@pytest.fixture(scope="module")
def measured(series, sections):
    """Every trace's measures by each fork path, keyed (section, name, index)."""
    out = {path: {} for path in PATHS}
    for n, section in sections.items():
        tform = section.tforms[series.alignment]
        items = [(name, i, trace) for name in sorted(section.contours)
                 for i, trace in enumerate(section.contours[name])]
        if not items:
            continue
        geometries = measureGeometries([np.asarray(t.points, dtype=float) for _, _, t in items],
                                       [t.closed for _, _, t in items], tform)
        for (name, i, trace), geometry in zip(items, geometries, strict=True):
            key = (n, name, i)
            feret = trace.getFeret(tform)
            data = TraceData(trace, i, tform)
            out["trace_data"][key] = _values(data, _feret(data, section, name))
            batch = TraceData.fromGeometry(i, trace.closed, trace.hidden, trace.negative,
                                           trace.tags, None, geometry, tform)
            out["batch"][key] = _values(batch, feret)
            opened = series.data.getTraceData(name, n)[i]
            out["series_data"][key] = _values(opened, _feret(opened, section, name))
    return out


def _syntheticTrace(case) -> Trace:
    trace = Trace(case["name"], (255, 0, 0), closed=case["closed"])
    trace.points = [tuple(p) for p in case["points"]]
    trace.negative = case["negative"]
    return trace


@pytest.fixture(scope="module")
def measured_synthetic(reference):
    out = {"trace_data": {}, "batch": {}}
    for case in reference["synthetic"]:
        if case["kind"] != "trace":
            continue
        trace = _syntheticTrace(case)
        tform = Transform(case["tform"])
        feret = trace.getFeret(tform)
        out["trace_data"][case["name"]] = _values(TraceData(trace, 0, tform), feret)
        geometry, = measureGeometries([np.asarray(trace.points, dtype=float)], [trace.closed], tform)
        out["batch"][case["name"]] = _values(
            TraceData.fromGeometry(0, trace.closed, False, trace.negative, set(), None, geometry, tform),
            feret)
    return out


def measureFailures(entries : list, measured_path : dict, label) -> list:
    """Each measure that misses upstream's value, or its recorded fork expectation."""
    failures = []
    for entry in entries:
        key = label(entry)
        values = measured_path[key]
        for measure in oracle.MEASURES:
            value = values[measure]
            recorded = entry["fork"].get(measure)
            expected = recorded["value"] if recorded else entry["upstream"][measure]
            allowed = oracle.tolerance(measure)
            if measure in entry["near_tie"]:
                allowed = 1e-6 if measure in ("cx", "cy") else 1e-7
            if abs(value - expected) > allowed:
                failures.append(f"{key} {measure}: fork {value!r}, expected {expected!r} "
                                f"({'fork, ' + recorded['reason'] if recorded else 'upstream'})")
    return failures


def _report(failures : list) -> str:
    return f"{len(failures)} mismatches:\n" + "\n".join(failures[:20])


# ------------------------------------------------------------------ provenance

def test_reference_is_pinned_to_the_fixture_and_commit(reference):
    assert reference["upstream_sha"] == UPSTREAM_SHA
    data = SERIES_FIXTURE.read_bytes()
    assert reference["fixture"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert reference["fixture"]["bytes"] == len(data)
    assert (REFERENCE_PATH.parents[2] / reference["generator"]["path"]).is_file()
    packages = reference["environment"]["packages"]
    for name in ("numpy", "opencv-python-headless", "PySide6", "scipy", "shapely"):
        assert packages[name]

    traces = reference["traces"]
    assert len(traces) == 232
    assert sum(t["point_count"] for t in traces) == 20105
    assert sum(t["closed"] for t in traces) == 228
    assert sorted(t["point_count"] for t in traces if not t["closed"]) == [2, 2, 2, 2]
    assert not any(t["negative"] for t in traces)
    assert len(reference["merge_traces"]) == 7
    assert len({_key(t["id"]) for t in traces}) == len(traces)
    assert all(t["synthetic"] and t["name"].startswith("synthetic_") for t in reference["synthetic"])
    assert not {t["id"]["name"] for t in traces} & {s["name"] for s in reference["synthetic"]}


def test_fork_loads_the_same_traces(reference, series, sections):
    expected = {_key(t["id"]): t for t in reference["traces"]}
    assert series.alignment == "default"
    loaded = {}
    for n, section in sections.items():
        for name, contour in section.contours.items():
            for i, trace in enumerate(contour):
                loaded[(n, name, i)] = trace
    assert sorted(loaded) == sorted(expected)
    for key, entry in expected.items():
        trace = loaded[key]
        assert oracle.pointsDigest(trace.points) == entry["points_sha256"], key
        assert (trace.closed, trace.negative, trace.hidden) == (
            entry["closed"], entry["negative"], entry["hidden"]), key
        assert sections[key[0]].tforms["default"].getList() == entry["tform"], key


# ------------------------------------------------------------------ measurements

@pytest.mark.parametrize("path", PATHS)
def test_real_trace_measures_match_upstream(reference, measured, path):
    failures = measureFailures(reference["traces"], measured[path], lambda e: _key(e["id"]))
    assert not failures, _report(failures)


@pytest.mark.parametrize("path", ("trace_data", "batch"))
def test_synthetic_measures_match_upstream(reference, measured_synthetic, path):
    cases = [c for c in reference["synthetic"] if c["kind"] == "trace"]
    failures = measureFailures(cases, measured_synthetic[path], lambda e: e["name"])
    assert not failures, _report(failures)


def _differenceFailures(entry, points, fork_values, reasons) -> list:
    """Each recorded difference must be documented, true by the oracle, and
    within its reason's bound; every fork value must agree with the oracle."""
    failures = []
    label = entry.get("name") or _key(entry["id"])
    exact = oracle.forkMeasures(points, entry["tform"], entry["closed"], entry["negative"])
    bound_x, bound_y = oracle.centroidBound(entry["tform"])
    for measure in oracle.MEASURES:
        allowed = oracle.tolerance(measure)
        if measure in exact["near_tie"]:
            allowed = 1e-6 if measure in ("cx", "cy") else 1e-7
        if abs(fork_values[measure] - exact[measure]) > allowed:
            failures.append(f"{label} {measure}: fork {fork_values[measure]!r}, oracle {exact[measure]!r}")
        recorded = entry["fork"].get(measure)
        if recorded is None:
            continue
        upstream = entry["upstream"][measure]
        if recorded["reason"] not in reasons:
            failures.append(f"{label} {measure}: reason {recorded['reason']!r} is not documented")
        if abs(recorded["value"] - exact[measure]) > allowed:
            failures.append(f"{label} {measure}: recorded {recorded['value']!r}, oracle {exact[measure]!r}")
        if recorded["reason"] == "centroid-rounding-order":
            bound = bound_x if measure == "cx" else bound_y
            if abs(recorded["value"] - upstream) > bound:
                failures.append(f"{label} {measure}: {upstream!r} and {recorded['value']!r} differ by more than {bound}")
        if recorded["reason"] == "minimum-width" and recorded["value"] > upstream + 1e-12:
            failures.append(f"{label} {measure}: width {recorded['value']!r} exceeds pair distance {upstream!r}")
    return failures


def test_recorded_differences_are_documented_and_true(reference, sections, measured, measured_synthetic):
    failures = []
    reasons = reference["reasons"]
    for entry in reference["traces"]:
        key = _key(entry["id"])
        trace = sections[key[0]].contours[key[1]][key[2]]
        failures += _differenceFailures(entry, trace.points, measured["trace_data"][key], reasons)
        ## upstream's centroid is explained by its own rule
        rule = oracle.upstreamCentroidRule(trace.points, entry["tform"])
        for axis, value in zip(("cx", "cy"), rule, strict=True):
            if abs(entry["upstream"][axis] - value) > 1e-12:
                failures.append(f"{key} {axis}: upstream {entry['upstream'][axis]!r}, its rule {value!r}")
    for case in reference["synthetic"]:
        if case["kind"] == "trace":
            failures += _differenceFailures(case, case["points"],
                                            measured_synthetic["trace_data"][case["name"]], reasons)
    assert not failures, _report(failures)


def test_far_from_origin_case_shows_the_precision_fix(reference):
    """The one recorded difference with no real trace behind it."""
    case = next(c for c in reference["synthetic"] if c["name"] == "synthetic_small_far_from_origin")
    assert set(case["fork"]) == {"area", "radius", "cx", "cy"}
    assert {d["reason"] for d in case["fork"].values()} == {"far-from-origin-precision"}
    ## upstream's centroid is off by more than the circle's own radius
    assert abs(case["upstream"]["cx"] - 100000.0) > 0.1
    assert case["fork"]["cx"]["value"] == 100000.0


# ------------------------------------------------------------------ export

def test_trace_csv_export_matches_upstream_rows(reference, series):
    upstream = {(r["Name"], int(r["Section"]), int(r["Index"])): r
                for r in csv.DictReader(io.StringIO("\n".join(reference["export_csv"])))}
    fork = {(r["Name"], int(r["Section"]), int(r["Index"])): r
            for r in csv.DictReader(io.StringIO(series.data.exportTracesCSV(), newline=""))}
    assert sorted(fork) == sorted(upstream)
    entries = {(t["id"]["name"], t["id"]["section"], t["id"]["index"]): t for t in reference["traces"]}
    failures = []
    for key, row in fork.items():
        entry = entries[key]
        for column in ("Hidden", "Closed", "Tags"):
            if row[column] != upstream[key][column]:
                failures.append(f"{key} {column}: {row[column]!r} != {upstream[key][column]!r}")
        for column, measure in CSV_COLUMNS.items():
            recorded = entry["fork"].get(measure)
            expected = oracle.exportNumber(recorded["value"]) if recorded else upstream[key][column]
            if measure in entry["near_tie"]:
                if abs(float(row[column]) - float(expected)) > 1e-6:
                    failures.append(f"{key} {column}: {row[column]} vs {expected}")
            elif row[column] != expected:
                failures.append(f"{key} {column}: fork {row[column]}, expected {expected}")
    assert not failures, _report(failures)


# ------------------------------------------------------------------ trace tools

def reduceFailures(entries : list, sections) -> list:
    failures = []
    for entry in entries:
        key = _key(entry["id"])
        trace = sections[key[0]].contours[key[1]][key[2]]
        output = reducePoints(trace.points, ep=0.8, iterations=1, closed=trace.closed,
                              mag=entry["mag_argument"])
        if output != entry["output"]:
            failures.append(f"{key}: reducePoints gave {len(output)} points, upstream {len(entry['output'])}"
                            if len(output) != len(entry["output"]) else f"{key}: reducePoints coordinates differ")
    return failures


def test_reduce_points_matches_upstream(reference, sections):
    assert len(reference["reduce_points"]) == 232
    for entry in reference["reduce_points"]:
        assert oracle.outputDigest(entry["output"]) == entry["output_sha256"]
    failures = reduceFailures(reference["reduce_points"], sections)
    assert not failures, _report(failures)


def test_reduce_points_matches_upstream_on_synthetic_traces(reference):
    for case in (c for c in reference["synthetic"] if c["kind"] == "trace"):
        trace = _syntheticTrace(case)
        output = reducePoints(trace.points, ep=0.8, iterations=1, closed=trace.closed,
                              mag=case["reduce_points"]["mag_argument"])
        assert output == case["reduce_points"]["output"], case["name"]


def _pixels(sections, ids) -> list:
    out = []
    for ident in ids:
        n, name, i = _key(ident)
        section = sections[n]
        trace = section.contours[name][i]
        out.append(np.rint(np.array(trace.points) / section.mag).astype(np.int32).tolist())
    return out


def mergeFailures(entries : list, sections) -> list:
    failures = []
    for entry in entries:
        pixels = _pixels(sections, entry["ids"])
        if hashlib.sha256(json.dumps(pixels).encode()).hexdigest() != entry["input_sha256"]:
            failures.append(f"{entry['ids']}: merge input differs")
        elif mergeTraces(pixels) != entry["output"]:
            failures.append(f"{entry['ids']}: mergeTraces output differs")
    return failures


def test_legacy_merge_matches_upstream(reference, sections):
    """The grid merge both trees share, on image pixel coordinates. The fork's
    current merge, mergeTracesInField, is tested below on its own."""
    assert [e["contours"] for e in reference["merge_traces"]] == [2] * 7
    failures = mergeFailures(reference["merge_traces"], sections)
    assert not failures, _report(failures)


def _overlap(reference):
    return next(c for c in reference["synthetic"] if c["name"] == "synthetic_overlap_pair")


def test_legacy_merge_matches_upstream_on_an_overlapping_pair(reference):
    case = _overlap(reference)
    assert case["contours"] == 1
    pixels = [[list(p) for p in t] for t in case["pixel_traces"]]
    assert mergeTraces(pixels) == case["merge_traces"]


def _shoelace(points) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                   in zip(points, points[1:] + points[:1], strict=True))) / 2


def test_field_merge_unions_the_overlapping_pair(reference):
    """mergeTracesInField has no counterpart at 35c87fa9: upstream merges on
    the screen's pixel grid. Its union of the pair must cover the area of
    upstream's pixel union, to within one pixel along the outline (upstream
    simplifies its outline by 0.8 pixel)."""
    case = _overlap(reference)
    mag = case["mag"]
    field = [[(x * mag, y * mag) for x, y in t] for t in case["pixel_traces"]]
    outlines = mergeTracesInField(field, mag)
    assert len(outlines) == 1
    upstream_outline = case["merge_traces"][0]
    upstream_area = _shoelace([tuple(p) for p in upstream_outline]) * mag * mag
    perimeter = sum(np.hypot(*np.subtract(a, b)) for a, b in
                    zip(upstream_outline, upstream_outline[1:] + upstream_outline[:1], strict=True))
    assert abs(_shoelace(outlines[0]) - upstream_area) <= perimeter * mag * mag


# ------------------------------------------------------------------ the tests catch change

def _bumped(reference, mutate):
    changed = copy.deepcopy(reference)
    mutate(changed)
    return changed


@pytest.mark.parametrize("measure,step", [
    ("length", 2e-7), ("area", 2e-9), ("radius", 2e-9), ("feret_max", 2e-9),
])
def test_a_changed_upstream_value_fails(reference, measured, measure, step):
    def mutate(r):
        r["traces"][0]["upstream"][measure] += step
    changed = _bumped(reference, mutate)
    failures = measureFailures(changed["traces"], measured["trace_data"], lambda e: _key(e["id"]))
    assert len(failures) == 1 and measure in failures[0]


@pytest.mark.parametrize("measure", ["cx", "feret_min"])
def test_a_changed_fork_expectation_fails(reference, measured, measure):
    def mutate(r):
        r["traces"][0]["fork"][measure]["value"] += 2e-6
    changed = _bumped(reference, mutate)
    failures = measureFailures(changed["traces"], measured["trace_data"], lambda e: _key(e["id"]))
    assert len(failures) == 1 and measure in failures[0]


def test_an_unrecorded_difference_fails(reference, measured):
    def mutate(r):
        del r["traces"][0]["fork"]["feret_min"]
    changed = _bumped(reference, mutate)
    failures = measureFailures(changed["traces"], measured["trace_data"], lambda e: _key(e["id"]))
    assert len(failures) == 1 and "feret_min" in failures[0]


def test_changed_tool_outputs_fail(reference, sections):
    def mutate(r):
        r["reduce_points"][0]["output"][0][0] += 1e-9
        r["merge_traces"][0]["output"][0][0][0] += 1
    changed = _bumped(reference, mutate)
    assert len(reduceFailures(changed["reduce_points"], sections)) == 1
    assert len(mergeFailures(changed["merge_traces"], sections)) == 1

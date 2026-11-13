"""Write the upstream measurement reference for class_series.jser.

The fork's real-trace measurement tests compare against numbers that
SynapseWeb/PyReconstruct produced at one pinned commit, so a change that moves
the fork and its own equivalence tests together still shows up. This script
makes that file. The tests never run it; they read the saved JSON.

Upstream runs in its own process and Python environment. This script, run
with the fork's Python, checks the upstream checkout, writes the synthetic
inputs, starts itself again under the upstream Python with -I (so neither
this directory nor the fork is importable there), and adds the oracle's
expectations (oracle.py) to what upstream returns.

Usage, from the repository root:

    git worktree add --detach <dir> 35c87fa9f444d2ef0be486b7133f0c177e4f9884
    uv venv --python 3.11 <venv>
    VIRTUAL_ENV=<venv> uv pip install numpy==1.24.1 scipy==1.14.1 \\
        scikit-image==0.23.2 shapely==2.1.1 opencv-python-headless==4.8.1.78 \\
        PySide6==6.5.2 lxml==6.1.0 zarr==2.18.2 numcodecs==0.15.0 tifffile==2024.9.20
    python tests/upstream_reference/generate.py --upstream <dir> --python <venv>/bin/python

The upstream process never constructs QSettings: the class is replaced by one
that raises before any upstream module is imported.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

UPSTREAM_SHA = "35c87fa9f444d2ef0be486b7133f0c177e4f9884"
REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path("dev") / "assets" / "checker" / "files" / "class_series.jser"
OUTPUT = Path(__file__).resolve().parent / "class_series_35c87fa9.json"
ALIGNMENT = "default"
REDUCE_ARGS = {"ep": 0.8, "iterations": 1}
PACKAGES = ("numpy", "scipy", "scikit-image", "shapely", "opencv-python-headless", "PySide6",
            "lxml", "zarr", "numcodecs", "tifffile")

REASONS = {
    "centroid-rounding-order": (
        "Upstream rounds the raw centroid to 6 decimals and then maps it; the fork maps "
        "the points and rounds the mapped centroid. Each is within 5e-7 of the exact "
        "value, so they differ by at most 5e-7 * (1 + |a| + |b|) per axis."
    ),
    "minimum-width": (
        "Upstream reports the closest antipodal pair of hull vertices; the fork reports "
        "the minimum width, the smallest gap between two parallel supporting lines "
        "(fork commit c9f27ab13f0e1b115d3bb1790533ea85bd8846c7). The width is never "
        "larger than any antipodal pair distance."
    ),
    "far-from-origin-precision": (
        "Upstream sums shoelace terms in raw coordinates, which loses a small trace far "
        "from the origin to rounding; the fork sums relative to the first point "
        "(fork commit 97713536552500a1ab2f6aff6df1b2b8b52926e7)."
    ),
}

## The reason each measure may differ by on any trace
MEASURE_REASONS = {"cx": "centroid-rounding-order", "cy": "centroid-rounding-order",
                   "feret_min": "minimum-width"}


def _polygon(cx, cy, radii, phase=0.0):
    """A closed star-shaped polygon, coordinates rounded to 8 decimals."""
    n = len(radii)
    return [
        (round(cx + r * math.cos(phase + 2 * math.pi * i / n), 8),
         round(cy + r * math.sin(phase + 2 * math.pi * i / n), 8))
        for i, r in enumerate(radii)
    ]


def syntheticCases() -> list:
    """Inputs class_series.jser lacks. None of these is a real trace."""
    ## no rotational symmetry, so the centroid is off the polygon's center
    lobed = [0.8 + 0.25 * math.sin(3 * t) + 0.1 * math.cos(t) + 0.04 * math.sin(2 * t + 0.4)
             + 0.01 * (i % 5) for i, t in ((i, 2 * math.pi * i / 36) for i in range(36))]
    angle = math.radians(30)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    circle = _polygon(100000.0, 100000.0, [0.1] * 40)
    polyline = [(round(10 + 0.05 * i, 8), round(20 + 0.3 * math.sin(i / 3), 8)) for i in range(40)]
    first = [(int(round(100 + 40 * math.cos(2 * math.pi * i / 32))),
              int(round(100 + 40 * math.sin(2 * math.pi * i / 32)))) for i in range(32)]
    second = [(int(round(150 + 35 * math.cos(2 * math.pi * i / 28))),
               int(round(112 + 35 * math.sin(2 * math.pi * i / 28)))) for i in range(28)]
    mag = 0.00204844

    def trace(name, points, tform, closed=True, negative=False, **extra):
        return dict(kind="trace", name=name, points=points, tform=tform, closed=closed,
                    negative=negative, mag=mag, **extra)

    return [
        trace("synthetic_negative_polygon", _polygon(12.53719, 20.24931, lobed),
              [1.0, 0.0, 3.25, 0.0, 1.0, -1.5], negative=True),
        trace("synthetic_open_polyline", polyline, [1.0, 0.0, 7.5, 0.0, 1.0, 2.0], closed=False),
        trace("synthetic_rotation", _polygon(12.53719, 20.24931, lobed, 0.3),
              [cos_a, -sin_a, 2.0, sin_a, cos_a, 1.0]),
        trace("synthetic_scale", _polygon(12.53719, 20.24931, lobed, 0.6),
              [1.7, 0.0, -4.0, 0.0, 0.6, 3.0]),
        trace("synthetic_shear", _polygon(12.53719, 20.24931, lobed, 0.9),
              [1.0, 0.35, 0.0, 0.2, 1.0, 0.0]),
        ## fork issue #426: a 40-point circle of radius 0.1 at (100000, 100000)
        trace("synthetic_small_far_from_origin", circle, [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
              documented={m: "far-from-origin-precision" for m in ("area", "radius", "cx", "cy")}),
        dict(kind="merge", name="synthetic_overlap_pair", pixel_traces=[first, second], mag=mag),
    ]


# ------------------------------------------------------------------ upstream side

def _trapSettings():
    """Make any QSettings construction in this process fail loudly."""
    import PySide6.QtCore

    class NoSettings:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("the upstream probe must not open QSettings")

    PySide6.QtCore.QSettings = NoSettings


def _rowPointCount(row) -> int:
    """The number of points in a contour row as the file stores it: an old
    keyed row, an 8-field row, or a 9-field row that names its own trace."""
    if isinstance(row, dict):
        return len(row["x"])
    return len(row[1] if len(row) == 9 else row[0])


def probe(upstream : str, fixture : str, synthetic : str, out : str):
    """Measure every trace with upstream's own code. Runs under upstream's Python."""
    sys.path.insert(0, upstream)
    _trapSettings()

    from importlib.metadata import version
    import numpy as np
    import PyReconstruct
    from PyReconstruct.modules.calc import mergeTraces, reducePoints
    from PyReconstruct.modules.datatypes.section import Section
    from PyReconstruct.modules.datatypes.series_data import ObjectData, SeriesData, TraceData
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.datatypes.transform import Transform

    package_dir = Path(PyReconstruct.__file__).resolve().parent
    if package_dir != Path(upstream).resolve() / "PyReconstruct":
        raise RuntimeError(f"imported PyReconstruct from {package_dir}, not {upstream}")

    with open(fixture) as f:
        jser = json.load(f)
    series_key = next(k for k in jser if k.endswith(".ser"))
    files = {int(n): name for n, name in jser[series_key]["sections"].items()}

    class StubSeries:
        """The attributes upstream's Section and ObjectData read off a Series."""
        alignment = ALIGNMENT
        groups_visibility = {}
        object_groups = None

        def __init__(self, wdir):
            self.wdir = wdir
            self.sections = files

        def getwdir(self):
            return self.wdir

        def getAttr(self, name, attr):
            return None

    def measures(data, trace, tform):
        feret_min, feret_max = data.getFeret()
        cx, cy = data.getCentroid()
        return {"length": data.getLength(), "area": data.getArea(), "radius": data.getRadius(),
                "cx": cx, "cy": cy, "feret_min": feret_min, "feret_max": feret_max}

    result = {"traces": [], "reduce_points": [], "merge_traces": [], "synthetic": []}
    with tempfile.TemporaryDirectory() as wdir:
        series = StubSeries(wdir)
        objects = {}
        for n in sorted(files):
            raw = jser[files[n]]
            with open(os.path.join(wdir, files[n]), "w") as f:
                json.dump(raw, f)
            section = Section(n, series)

            ## the file rows each loaded trace came from: Section.updateJSON
            ## and Section.__init__ drop rows of fewer than two points
            tform = section.tforms[ALIGNMENT]
            for name in sorted(section.contours):
                counts = [_rowPointCount(row) for row in raw["contours"][name]]
                kept = [row for row, count in enumerate(counts) if count > 1]
                contour = section.contours[name]
                if [counts[row] for row in kept] != [len(t.points) for t in contour.getTraces()]:
                    raise RuntimeError(f"row map mismatch on section {n}, {name}")
                obj = objects.setdefault(name, ObjectData())
                closed_pixels = []
                for index, (row, trace) in enumerate(zip(kept, contour.getTraces(), strict=True)):
                    obj.addTrace(trace, section, series)
                    data = obj.traces[n][index]
                    ident = {"section": n, "name": name, "row": row, "index": index}
                    result["traces"].append({
                        "id": ident, "closed": trace.closed, "negative": trace.negative,
                        "hidden": trace.hidden, "point_count": len(trace.points),
                        "points": [list(p) for p in trace.points],
                        "tform": list(tform.getList()), "mag": section.mag,
                        "upstream": measures(data, trace, tform),
                    })
                    mag = 1 / section.mag
                    out_points = reducePoints(trace.points, ep=REDUCE_ARGS["ep"],
                                              iterations=REDUCE_ARGS["iterations"],
                                              closed=trace.closed, mag=mag)
                    result["reduce_points"].append({"id": ident, "mag_argument": mag,
                                                    "closed": trace.closed, "output": out_points})
                    if trace.closed:
                        closed_pixels.append((ident, np.rint(np.array(trace.points) / section.mag)
                                              .astype(np.int32).tolist()))
                if len(closed_pixels) > 1:
                    pixels = [p for _, p in closed_pixels]
                    result["merge_traces"].append({
                        "ids": [i for i, _ in closed_pixels],
                        "input_sha256": hashlib.sha256(json.dumps(pixels).encode()).hexdigest(),
                        "output": mergeTraces(pixels),
                    })

        ## upstream's own trace CSV export over the same data
        series_data = SeriesData.__new__(SeriesData)
        series_data.series = series
        series_data.data = {"sections": {}, "objects": objects}
        result["export_csv"] = series_data.exportTracesCSV()

    with open(synthetic) as f:
        cases = json.load(f)
    for case in cases:
        if case["kind"] == "trace":
            trace = Trace(case["name"], (255, 0, 0), closed=case["closed"])
            trace.points = [tuple(p) for p in case["points"]]
            trace.negative = case["negative"]
            tform = Transform(case["tform"])
            data = TraceData(trace, 0, tform)
            mag = 1 / case["mag"]
            result["synthetic"].append({
                "name": case["name"], "upstream": measures(data, trace, tform),
                "reduce_points": {"mag_argument": mag, "output": reducePoints(
                    trace.points, ep=REDUCE_ARGS["ep"], iterations=REDUCE_ARGS["iterations"],
                    closed=trace.closed, mag=mag)},
            })
        else:
            pixels = [[list(p) for p in t] for t in case["pixel_traces"]]
            result["synthetic"].append({"name": case["name"], "merge_traces": mergeTraces(pixels)})

    import cv2
    result["environment"] = {
        "python": sys.version, "platform": platform.platform(),
        "packages": {p: version(p) for p in PACKAGES}, "cv2": cv2.__version__,
    }
    with open(out, "w") as f:
        json.dump(result, f)


# ------------------------------------------------------------------ fork side

def _git(upstream, *args) -> str:
    return subprocess.run(["git", "-C", upstream, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _differences(upstream_values : dict, expected : dict, tform : list, documented : dict) -> dict:
    """The measures where upstream and the fork's expectation differ, with why."""
    from oracle import centroidBound, tolerance

    out = {}
    bound_x, bound_y = centroidBound(tform)
    for measure, value in upstream_values.items():
        delta = abs(value - expected[measure])
        if delta <= tolerance(measure) or measure in expected["near_tie"]:
            continue
        reason = documented.get(measure, MEASURE_REASONS.get(measure, "undocumented"))
        if reason == "centroid-rounding-order" and delta > (bound_x if measure == "cx" else bound_y):
            reason = "undocumented"
        if reason == "minimum-width" and expected[measure] > value + 1e-12:
            reason = "undocumented"
        out[measure] = {"value": expected[measure], "reason": reason}
    return out


def _dumpReference(reference : dict) -> str:
    """JSON with one line per trace, export row, tool output and synthetic case."""
    parts = []
    for key, value in reference.items():
        if isinstance(value, list):
            body = ",\n".join("  " + json.dumps(item, separators=(",", ":")) for item in value)
            text = "[\n" + body + "\n ]"
        else:
            text = json.dumps(value, indent=2).replace("\n", "\n ")
        parts.append(f" {json.dumps(key)}: {text}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def generate(upstream : str, python : str, output : Path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from oracle import forkMeasures, outputDigest, pointsDigest

    head = _git(upstream, "rev-parse", "HEAD")
    if head != UPSTREAM_SHA:
        raise SystemExit(f"{upstream} is at {head}, not {UPSTREAM_SHA}")
    if _git(upstream, "status", "--porcelain"):
        raise SystemExit(f"{upstream} has local changes")

    fixture = REPO / FIXTURE
    fixture_bytes = fixture.read_bytes()
    cases = syntheticCases()

    with tempfile.TemporaryDirectory() as tmp:
        synthetic_path = os.path.join(tmp, "synthetic.json")
        probe_path = os.path.join(tmp, "probe.json")
        with open(synthetic_path, "w") as f:
            json.dump(cases, f)
        subprocess.run([python, "-I", str(Path(__file__).resolve()), "--probe",
                        upstream, str(fixture), synthetic_path, probe_path], check=True)
        with open(probe_path) as f:
            probed = json.load(f)

    traces = []
    for entry in probed["traces"]:
        points = entry.pop("points")
        expected = forkMeasures(points, entry["tform"], entry["closed"], entry["negative"])
        entry["points_sha256"] = pointsDigest(points)
        entry["fork"] = _differences(entry["upstream"], expected, entry["tform"], {})
        entry["near_tie"] = expected["near_tie"]
        traces.append(entry)

    reduce_points = []
    for entry in probed["reduce_points"]:
        entry["output_sha256"] = outputDigest(entry["output"])
        reduce_points.append(entry)
    for entry in probed["merge_traces"]:
        entry["output_sha256"] = outputDigest(entry["output"])
        entry["contours"] = len(entry["output"])

    synthetic = []
    probed_synthetic = {s["name"]: s for s in probed["synthetic"]}
    for case in cases:
        got = probed_synthetic[case["name"]]
        if case["kind"] == "trace":
            expected = forkMeasures(case["points"], case["tform"], case["closed"], case["negative"])
            synthetic.append({
                "kind": "trace", "name": case["name"], "synthetic": True,
                "points": case["points"], "tform": case["tform"], "closed": case["closed"],
                "negative": case["negative"], "mag": case["mag"],
                "upstream": got["upstream"],
                "fork": _differences(got["upstream"], expected, case["tform"],
                                     case.get("documented", {})),
                "near_tie": expected["near_tie"],
                "reduce_points": got["reduce_points"],
            })
        else:
            synthetic.append({
                "kind": "merge", "name": case["name"], "synthetic": True,
                "pixel_traces": case["pixel_traces"], "mag": case["mag"],
                "merge_traces": got["merge_traces"], "contours": len(got["merge_traces"]),
            })

    reference = {
        "about": (
            "Measurements of class_series.jser by SynapseWeb/PyReconstruct at a pinned "
            "commit, written by tests/upstream_reference/generate.py. 'upstream' holds "
            "upstream's raw values; 'fork' holds the fork's expectation for each measure "
            "that differs on purpose, with the reason. Entries under 'synthetic' are made "
            "up inputs, not real traces."
        ),
        "upstream_sha": UPSTREAM_SHA,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {
            "path": "tests/upstream_reference/generate.py",
            "command": ["python", "tests/upstream_reference/generate.py",
                        "--upstream", "<checkout>", "--python", "<python>"],
            "isolation": "separate process, upstream's own Python run with -I; QSettings replaced "
                         "by a class that raises",
        },
        "fixture": {"path": FIXTURE.as_posix(), "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                    "bytes": len(fixture_bytes)},
        "selection": (
            "Every trace upstream's Section loads from every section, alignment 'default', "
            "in section number, object name, loaded index order. Section.__init__ drops rows "
            "of fewer than two points and opens two-point rows. 'row' is the trace's row in "
            "the contour as the fixture stores it; 'index' is its position in the loaded "
            "contour, which is TraceData's index."
        ),
        "trace_data": (
            "Upstream ObjectData.addTrace builds each TraceData(trace, index, tform); "
            "measures are its getLength, getArea, getRadius, getCentroid and getFeret."
        ),
        "export": "Upstream SeriesData.exportTracesCSV over the same TraceData, rows split on commas.",
        "reduce_points_arguments": {
            "call": "reducePoints(trace.points, ep=0.8, iterations=1, closed=trace.closed, "
                    "mag=1/section.mag)",
            "note": "Points are scaled by mag and truncated to int32, simplified by "
                    "cv2.approxPolyDP, then divided by mag.",
        },
        "merge_traces_arguments": {
            "call": "mergeTraces(pixels)",
            "conversion": "pixels = np.rint(np.array(trace.points) / section.mag)"
                          ".astype(np.int32).tolist(), raw (untransformed) points, every "
                          "section and object with two or more closed traces",
            "note": "This is the legacy grid merge, which upstream's field calls on screen "
                    "pixel coordinates. The fork's current merge, mergeTracesInField, has no "
                    "counterpart at this commit and is not compared here.",
        },
        "tool_output_digest": "SHA-256 of json.dumps(output, sort_keys=True, "
                              "separators=(',', ':'), allow_nan=False)",
        "points_digest": "SHA-256 of json.dumps([[x, y], ...], separators=(',', ':')) of the "
                         "loaded points",
        "environment": probed["environment"],
        "reasons": REASONS,
        "traces": traces,
        "export_csv": probed["export_csv"].splitlines(),
        "reduce_points": reduce_points,
        "merge_traces": probed["merge_traces"],
        "synthetic": synthetic,
    }
    undocumented = [(t["id"], m) for t in traces for m, d in t["fork"].items()
                    if d["reason"] == "undocumented"]
    undocumented += [(s["name"], m) for s in synthetic if s["kind"] == "trace"
                     for m, d in s["fork"].items() if d["reason"] == "undocumented"]
    with open(output, "w") as f:
        f.write(_dumpReference(reference))
    print(f"wrote {output}: {len(traces)} traces, {len(probed['merge_traces'])} merges, "
          f"{len(synthetic)} synthetic cases, {len(undocumented)} undocumented differences")
    for item in undocumented:
        print("undocumented:", item)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--upstream", help="a clean checkout of " + UPSTREAM_SHA)
    parser.add_argument("--python", help="the Python of upstream's environment")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--probe", nargs=4, metavar=("UPSTREAM", "FIXTURE", "SYNTHETIC", "OUT"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        probe(*args.probe)
    elif args.upstream and args.python:
        generate(args.upstream, args.python, args.output)
    else:
        parser.error("--upstream and --python are required")


if __name__ == "__main__":
    main()

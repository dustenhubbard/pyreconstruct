"""Measure full and filtered Refresh through a real Object List.

Run explicitly with:
uv run --frozen --no-default-groups --extra test python -m pytest benchmarks/bench_filtered_refresh.py -s

The generated series has 30,000 objects with one 48-point contour each,
spread over 100 sections. Five objects on one section match the regex.
Both paths check for pending edits and update real widgets. Fixture generation,
opening, cache corruption and correctness checks are outside the timer.
"""
import cProfile
import io
import json
import math
import pstats
import statistics
import sys
import time
from pathlib import Path

import pytest

# Use the suite's settings isolation and real MainWindow fixture.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
pytest_plugins = ["tests.conftest"]


@pytest.fixture
def series_jser(tmp_path):
    points = [(math.cos(i * math.tau / 48), math.sin(i * math.tau / 48))
              for i in range(48)]
    row = [
        [x for x, _ in points], [y for _, y in points], [255, 0, 0],
        True, False, False, ["none", "none"], [],
    ]
    sections = []
    for snum in range(100):
        sections.append({
            "src": f"missing-{snum}.png", "mag": 0.00254, "thickness": 0.05,
            "contours": {f"obj_{snum:03d}_{n:03d}": [row] for n in range(300)},
        })
    path = tmp_path / "refresh.jser"
    path.write_text(json.dumps({"series": {}, "sections": sections, "log": ""}))
    return path


def test_refresh_timings(main_window):
    manager = main_window.field.table_manager
    manager.newTable("object")
    widget = manager.tables["object"][0]
    widget.re_filters = {r"obj_050_00[0-4]"}
    widget.createTable()
    names = widget.getFiltered()
    assert len(names) == 5
    assert len(main_window.series.data.objects) == 30_000
    area = 24 * math.sin(math.tau / 48)
    timings = {"full": [], "filtered": []}

    def run(mode):
        data = main_window.series.data
        for name in names:
            for traces in data.objects[name].traces.values():
                for td in traces:
                    td.area = 0
        start = time.perf_counter()
        if mode == "full":
            manager.refresh()
        else:
            widget.refresh_act.trigger()
        elapsed = time.perf_counter() - start
        assert len(data.objects) == 30_000
        assert widget.model.names == names
        for name in names:
            assert data.getFlatArea(name) == pytest.approx(area)
        return elapsed

    # Warm both paths, then alternate their order to reduce cache/load bias.
    run("full")
    run("filtered")
    for i in range(5):
        for mode in (("full", "filtered") if i % 2 == 0 else ("filtered", "full")):
            timings[mode].append(run(mode))
    print(json.dumps({
        mode: {"seconds": values, "median": statistics.median(values),
               "min": min(values), "max": max(values)}
        for mode, values in timings.items()
    }, sort_keys=True))
    # Profile separate runs, excluded from the reported timings.
    for mode in timings:
        profiler = cProfile.Profile()
        profiler.runcall(run, mode)
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).sort_stats("cumtime").print_stats(12)
        print(mode, output.getvalue())

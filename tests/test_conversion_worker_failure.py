"""Zarr conversions must stop when a worker fails (fork #503).

``ThreadPoolProgBar.startAll`` shows its Task Error window and returns False
when any worker raises. The conversions dropped that value, so a failed
export still returned its path (a Zarr of zeros), the retrain branch of
``seriesToLabels`` removed its source group, and the zarr label import said
"Labels imported successfully."

The pool here runs each worker inline and returns what the real one does:
False if any worker raised.
"""
import types

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        ok = True
        for fn, a in self.jobs:
            try:
                fn(*a)
            except Exception:
                ok = False
        return ok


def _boom(*args, **kwargs):
    raise RuntimeError("worker failed")


@pytest.fixture
def inline_pool(monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)


def _labels_ready_zarr(path, sections):
    """A zarr with the raw attributes seriesToZarr writes."""
    zg = zarr.open(str(path), "w")
    raw = zg.create_dataset(
        "raw", shape=(len(sections), 4, 4), chunks=(1, 4, 4), dtype=np.uint8
    )
    raw.attrs["window"] = [0.0, 0.0, 0.032, 0.032]
    raw.attrs["sections"] = sections
    raw.attrs["true_mag"] = 0.008
    raw.attrs["voxel_size"] = [50, 8, 8]
    raw.attrs["offset"] = [0, 0, 0]
    raw.attrs["alignment"] = {str(s): [1, 0, 0, 0, 1, 0] for s in sections}
    return zg


def test_series_to_zarr_removes_the_zarr_when_a_worker_fails(
    tmp_path, real_series, inline_pool, monkeypatch
):
    monkeypatch.setattr(conversions, "exportSection", _boom)
    out = tmp_path / "out.zarr"
    snum = sorted(real_series.sections)[0]

    result = conversions.seriesToZarr(
        real_series, [snum], 0.008, [0.0, 0.0, 1.0, 1.0], data_fp=str(out)
    )

    assert result is None
    assert not out.exists(), "a Zarr of blank sections was left behind"


def test_series_to_labels_keeps_the_group_when_a_worker_fails(
    tmp_path, real_series, inline_pool, monkeypatch
):
    monkeypatch.setattr(conversions, "exportTraces", _boom)
    sections = sorted(real_series.sections)[:2]
    out = tmp_path / "labels.zarr"
    _labels_ready_zarr(out, sections)
    real_series.object_groups.add("seg_20260101", "obj")

    ok = conversions.seriesToLabels(real_series, str(out))  # retrain branch

    assert ok is False
    assert "seg_20260101" in real_series.object_groups.getGroupList()
    assert "labels_seg_20260101_keep" not in zarr.open(str(out))


def test_series_to_labels_reports_success(
    tmp_path, real_series, inline_pool, monkeypatch
):
    monkeypatch.setattr(conversions, "exportTraces", lambda *a: None)
    sections = sorted(real_series.sections)[:2]
    out = tmp_path / "labels.zarr"
    _labels_ready_zarr(out, sections)
    real_series.object_groups.add("seg_20260101", "obj")

    assert conversions.seriesToLabels(real_series, str(out)) is True
    assert "seg_20260101" not in real_series.object_groups.getGroupList()


@pytest.mark.parametrize("worker, expected", [(_boom, False), (lambda *a: None, True)])
def test_labels_to_objects_returns_whether_it_worked(
    inline_pool, monkeypatch, worker, expected
):
    monkeypatch.setattr(conversions, "setDT", lambda: None)
    monkeypatch.setattr(
        conversions, "getLabelsToObjectsData", lambda *a, **k: (None, [0, 1], 0)
    )
    monkeypatch.setattr(conversions, "importSection", worker)

    assert conversions.labelsToObjects(object(), "fp", "labels_x") is expected


def test_new_series_from_zarr_stops_when_the_import_fails(tmp_path, monkeypatch):
    src = tmp_path / "src.zarr"
    zg = _labels_ready_zarr(src, [0, 1])
    zg.create_dataset("labels_x", shape=(2, 4, 4), dtype=np.uint64)
    monkeypatch.setattr(conversions, "labelsToObjects", lambda *a, **k: False)

    series = conversions.zarrToNewSeries(str(src), ["labels_x"], "fresh")

    assert series is None
    assert not (tmp_path / "fresh_images.zarr").exists()
    assert not (tmp_path / ".fresh").exists()


@pytest.mark.parametrize("imported, notified", [(False, []), (True, ["Labels imported successfully."])])
def test_import_labels_only_reports_success_on_success(monkeypatch, imported, notified):
    from PyReconstruct.modules.gui.main import main_window

    messages = []
    monkeypatch.setattr(main_window, "labelsToObjects", lambda *a, **k: imported)
    monkeypatch.setattr(main_window, "notify", messages.append)

    noop = lambda *a, **k: None
    window = types.SimpleNamespace(
        field=types.SimpleNamespace(
            zarr_layer=types.SimpleNamespace(is_labels=True, selected_ids=[1]),
            reload=noop,
            table_manager=types.SimpleNamespace(refresh=noop),
        ),
        series=types.SimpleNamespace(zarr_overlay_fp="fp", zarr_overlay_group="labels_x"),
        removeZarrLayer=noop,
    )

    main_window.MainWindow.importLabels(window)

    assert messages == notified


@pytest.mark.parametrize(
    "results, attempted",
    [
        ([None, True], ["stray", "labels_a"]),  # a group not in the zarr is skipped
        ([False, True], ["stray"]),  # a failed import stops the loop
    ],
)
def test_menu_import_stops_only_on_a_failed_group(monkeypatch, results, attempted):
    from PyReconstruct.modules.gui.main import main_window

    groups = ["stray", "labels_a"]
    calls = []
    outcomes = iter(results)

    def fake_labels_to_objects(series, zarr_fp, group):
        calls.append(group)
        return next(outcomes)

    monkeypatch.setattr(main_window.FileDialog, "get", lambda *a, **k: "data.zarr")
    monkeypatch.setattr(
        main_window.QuickDialog, "get", lambda *a, **k: ([list(groups)], True)
    )
    monkeypatch.setattr(main_window.os, "listdir", lambda fp: list(groups))
    monkeypatch.setattr(main_window, "labelsToObjects", fake_labels_to_objects)

    window = types.SimpleNamespace(
        series=object(),
        field=types.SimpleNamespace(reload=lambda: None),
    )

    main_window.MainWindow.importFromZarrLabels(window)

    assert calls == attempted

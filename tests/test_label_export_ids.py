"""Label export gives every object its own nonzero id, listed in gt_lookup.

seriesToLabels used to label each trace with hashName(name), which drops case
and punctuation, so ``Axon`` and ``axon`` shared a label and ``0`` and ``_``
came out as 0, the background (fork #500). Each section's worker also wrote
its own map to ``gt_lookup``, so only the last worker's map was kept (fork
#502). These run the real seriesToLabels, exportTraces and generateLabelsArray
against a real zarr, with the workers run in both orders.
"""

import types

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Trace  # noqa: E402

IDENTITY = [1, 0, 0, 0, 1, 0]

## section number -> names drawn on it, one 4x4 box each, left to right
SECTION_NAMES = {
    0: ["Axon", "axon_1", "0", "_"],
    1: ["axon", "axon1", "AXON-1", "Axon1"],
}
BOX_X = [2, 12, 22, 32]


class _Contour:
    def __init__(self, trace):
        self._traces = [trace]

    def getTraces(self):
        return list(self._traces)


def _box(name, x):
    trace = Trace(name, (255, 0, 0), closed=True)
    trace.points = [(x, 3), (x + 4, 3), (x + 4, 7), (x, 7)]
    return trace


def _section(names):
    contours = {n: _Contour(_box(n, x)) for n, x in zip(names, BOX_X)}
    return types.SimpleNamespace(mag=1.0, contours=contours, tform=None)


class _Series:
    def __init__(self):
        self.window = None
        self.sections = {s: _section(n) for s, n in SECTION_NAMES.items()}
        members = {n for names in SECTION_NAMES.values() for n in names}
        self.object_groups = types.SimpleNamespace(
            getGroupObjects=lambda g: set(members) if g == "cells" else set()
        )

    def loadSection(self, snum):
        return self.sections[snum]


def _pool_running(order):
    class _Pool:
        def __init__(self):
            self.workers = []

        def createWorker(self, fn, *args, **kwargs):
            self.workers.append((fn, args))

        def startAll(self, *args, **kwargs):
            workers = self.workers if order == "forward" else self.workers[::-1]
            for fn, args in workers:
                fn(*args)
            return True

    return _Pool


def _export(tmp_path, monkeypatch, order):
    fp = str(tmp_path / "export.zarr")
    zg = zarr.open(fp, mode="w")
    raw = zg.create_dataset("raw", shape=(2, 10, 40), dtype=np.uint8)
    raw.attrs.update({
        "alignment": {"0": IDENTITY, "1": IDENTITY},
        "window": [0, 0, 40, 10],
        "offset": [0, 0, 0],
        "sections": [0, 1],
        "true_mag": 1.0,
        "voxel_size": [50, 1, 1],
    })
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _pool_running(order))

    conversions.seriesToLabels(_Series(), fp, group="cells")

    labels = zarr.open(fp, mode="r")["labels_cells"]
    drawn = {}
    for z, snum in enumerate([0, 1]):
        for name, x in zip(SECTION_NAMES[snum], BOX_X):
            ## the box spans rows 3..7 and columns x..x+4; read its middle
            drawn[name] = int(labels[z, 5, x + 2])
    return drawn, dict(labels.attrs["gt_lookup"])


@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_every_object_gets_its_own_nonzero_label(tmp_path, monkeypatch, order):
    drawn, _ = _export(tmp_path, monkeypatch, order)

    assert all(label != 0 for label in drawn.values()), drawn
    assert len(set(drawn.values())) == len(drawn), drawn


@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_gt_lookup_covers_every_section(tmp_path, monkeypatch, order):
    drawn, gt_lookup = _export(tmp_path, monkeypatch, order)

    assert gt_lookup == drawn

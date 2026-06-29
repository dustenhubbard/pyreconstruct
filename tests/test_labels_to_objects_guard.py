"""Regression test for labelsToObjects unpacking a None result.

getLabelsToObjectsData returns None (bare return) when the requested group is
not present in the zarr. labelsToObjects unpacked the result directly --
``data_zg, sections, section_start = getLabelsToObjectsData(...)`` -- raising
TypeError ("cannot unpack non-iterable NoneType") when a stray, non-zarr
folder slips through importFromZarrLabels' listdir-based group list. Exercised
with the module collaborators monkeypatched; no real zarr / threads.
"""
import types

from PyReconstruct.modules.backend.autoseg import conversions as conv


class _ThreadPool:
    def __init__(self, *a, **k):
        self.workers = []

    def createWorker(self, *a, **k):
        self.workers.append(a)

    def startAll(self, *a, **k):
        pass


def _patch(monkeypatch, data):
    monkeypatch.setattr(conv, "getLabelsToObjectsData", lambda *a, **k: data)
    monkeypatch.setattr(conv, "setDT", lambda *a, **k: None)
    created = []

    def make_pool(*a, **k):
        pool = _ThreadPool()
        created.append(pool)
        return pool

    monkeypatch.setattr(conv, "ThreadPoolProgBar", make_pool)
    return created


def test_missing_group_is_noop(monkeypatch):
    created = _patch(monkeypatch, None)

    conv.labelsToObjects(object(), "fp", "badgroup")  # must not raise TypeError

    assert created == [], "no threadpool/workers should be created for a missing group"


def test_valid_group_creates_workers(monkeypatch):
    # section_start=0, max(sections)=2 -> snums 0,1,2 -> three workers
    created = _patch(monkeypatch, ("ZG", [0, 1, 2], 0))

    conv.labelsToObjects(object(), "fp", "goodgroup")

    assert len(created) == 1
    assert len(created[0].workers) == 3

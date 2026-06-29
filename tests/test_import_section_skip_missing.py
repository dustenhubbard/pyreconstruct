"""Regression test for importSection on a section absent from the series.

importSection guarded section numbers missing from the zarr's alignment, but
not numbers that exist in the zarr yet are absent from the CURRENT series.
Such a number passed the alignment guard and reached series.loadSection(snum)
-> Section(snum, series) -> series.sections[snum] -> KeyError. This happens
when a label zarr was produced from a different/stale series. Worker.run
catches the exception and emits a failed import rather than crashing, so the
section silently fails to import. Exercised with the module collaborators
monkeypatched.
"""
import types

import pytest

from PyReconstruct.modules.backend.autoseg import conversions as conv


class _Reached(Exception):
    """Raised by the stub loadSection to prove the guard let execution through."""


class _Series:
    def __init__(self, snums):
        self.sections = {n: None for n in snums}

    def loadSection(self, snum):
        raise _Reached


def _fake_zarr():
    return types.SimpleNamespace(
        attrs={
            "window": [0.0, 0.0, 1.0, 1.0],
            "sections": [5, 6, 7],
            "true_mag": 0.01,
            "alignment": {
                "5": [1, 0, 0, 0, 1, 0],
                "6": [1, 0, 0, 0, 1, 0],
                "7": [1, 0, 0, 0, 1, 0],
            },
        }
    )


def _patch(monkeypatch):
    fake = _fake_zarr()
    monkeypatch.setattr(conv, "get_zarr_array", lambda *a, **k: fake)
    monkeypatch.setattr(conv, "get_resolution", lambda a: [1.0, 1.0, 1.0])
    monkeypatch.setattr(conv, "get_array_offset", lambda a: [0.0, 0.0, 0.0])
    return fake


def test_section_absent_from_series_is_skipped(monkeypatch):
    fake = _patch(monkeypatch)
    series = _Series([1, 2, 3])  # the zarr's section 5 is not in this series

    # must return without reaching loadSection (pre-fix it did -> _Reached)
    conv.importSection(fake, "labels", 5, series, None)


def test_section_present_in_series_proceeds(monkeypatch):
    fake = _patch(monkeypatch)
    series = _Series([5, 6, 7])  # section 5 present -> guard passes through

    with pytest.raises(_Reached):
        conv.importSection(fake, "labels", 5, series, None)

"""Regression test for sectionXMLtoJSON with partial reconcropper alignment.

sectionXMLtoJSON did ``if alignment_dict: section_dict["tforms"] =
alignment_dict[fname]``. The guard only checks the dict is non-empty, not that
this section's filename is a key. A reconcropper JSON that omits a section file
present on disk made alignment_dict[fname] raise KeyError, aborting the whole
import (the surrounding try/except is commented out). Fall back to an empty
tforms dict for sections without alignment data.
"""
import json
import types

from PyReconstruct.modules.backend.func import xml_json_conversions as mod
from PyReconstruct.modules.datatypes.transform import Transform


def _fake_section():
    # no images -> identity transform; no contours -> the trace loop is skipped
    return types.SimpleNamespace(images=[], thickness=50, alignLocked=False, contours=[])


def test_section_missing_from_alignment_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "process_section_file", lambda fp: _fake_section())
    alignment_dict = {"series.7": {"LOCAL": [1, 0, 0, 0, 1, 0]}}  # missing "series.0"

    tform = mod.sectionXMLtoJSON("/d/series.0", alignment_dict, str(tmp_path))  # no KeyError

    assert isinstance(tform, Transform)
    with open(tmp_path / "series.0") as f:
        d = json.load(f)
    # only the default tform (from the image transform); no reconcropper alignment
    assert d["tforms"] == {"default": Transform.identity().getList()}


def test_section_present_in_alignment_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "process_section_file", lambda fp: _fake_section())
    alignment_dict = {"series.0": {"align1": [2, 0, 0, 0, 2, 0]}}

    mod.sectionXMLtoJSON("/d/series.0", alignment_dict, str(tmp_path))

    with open(tmp_path / "series.0") as f:
        d = json.load(f)
    # the section's alignment is copied AND the default is added
    assert d["tforms"]["align1"] == [2, 0, 0, 0, 2, 0]
    assert "default" in d["tforms"]

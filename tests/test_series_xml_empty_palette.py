"""Regression test for seriesXMLToJSON with an empty legacy palette.

After building palette_traces from the .ser's <Contour> elements,
seriesXMLToJSON unconditionally did palette_traces[0] for current_trace. A
legacy series with no palette contours leaves palette_traces empty, so [0]
raised IndexError and aborted the whole import. Fall back to the standard
default palette when the imported one is empty.
"""
import json
import types

from PyReconstruct.modules.backend.func import xml_json_conversions as mod


def test_empty_palette_falls_back_to_default(monkeypatch, tmp_path):
    fake_series = types.SimpleNamespace(
        index=0, viewport=[0.0, 0.0, 1.0, 1.0], contours=[], zcontours=[]
    )
    monkeypatch.setattr(mod, "process_series_file", lambda fp: fake_series)

    out = mod.seriesXMLToJSON("myseries.ser", [], str(tmp_path))  # must not raise

    with open(out) as f:
        d = json.load(f)

    assert d["palette_traces"], "an empty legacy palette should use the default palette"
    assert d["current_trace"] == d["palette_traces"][0]

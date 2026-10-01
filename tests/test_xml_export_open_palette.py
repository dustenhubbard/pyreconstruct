"""Export to XML writes an open palette trace as open.

`blank_palette_contour` had `closed="true"` written into it, so the
`[CLOSED]` replacement in `Trace.getXMLObj` found nothing to replace and every
palette contour in the `.ser` was closed.
"""
from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes_legacy import process_series_file


def test_legacy_palette_text_carries_closed():
    trace = Trace("line", [255, 0, 0], closed=False)
    trace.points = [(-1, 0), (0, 1), (1, 0)]
    assert 'closed="false"' in trace.getXMLObj(legacy_format=True)

    trace.closed = True
    assert 'closed="true"' in trace.getXMLObj(legacy_format=True)


def test_open_palette_trace_round_trips(qapp, real_series, tmp_path):
    palette = real_series.palette_traces[real_series.palette_index[0]]
    palette[0].closed = False
    expected = [(t.name, t.closed) for t in palette]
    assert expected[0][1] is False and any(c for _, c in expected)

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))
    ser = out / f"{real_series.name}.ser"

    exported = process_series_file(str(ser))
    assert [(c.name, c.closed) for c in exported.contours[:len(expected)]] == expected

    back = xmlToJSON(str(ser))
    try:
        got = [(t.name, t.closed) for t in back.palette_traces[back.palette_index[0]]]
    finally:
        back.close()
    assert got[:len(expected)] == expected

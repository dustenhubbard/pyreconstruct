"""Export to XML writes palette and z-trace colors that read back unchanged.

The `.ser` keeps those colors to three decimals and the import truncates
`v * 255`, so 76 went out as `0.298` and came back as 75, one lower on every
round trip, for 125 of the 256 channel values. Section traces are written in
full and were not affected.
"""
from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.datatypes import Ztrace
from PyReconstruct.modules.datatypes.trace import xmlColorChannel

COLOR = (76, 20, 200)


def test_every_channel_value_reads_back():
    for c in range(256):
        written = float("{:.3f}".format(xmlColorChannel(c)))  # the writer's format
        assert int(written * 255) == c, c  # what the import does
        assert round(written * 255) == c, c


def _round_trip(series, tmp_path, tag):
    out = tmp_path / tag
    out.mkdir()
    jsonToXML(series, str(out))
    return xmlToJSON(str(out / f"{series.name}.ser"))


def test_palette_and_ztrace_colors_round_trip(qapp, real_series, tmp_path):
    palette = real_series.palette_traces[real_series.palette_index[0]]
    palette[0].color = COLOR
    snums = sorted(real_series.sections)[:2]
    real_series.ztraces["zt"] = Ztrace("zt", COLOR, [(1.0, 1.0, n) for n in snums])

    back = _round_trip(real_series, tmp_path, "one")
    try:
        assert tuple(back.palette_traces[back.palette_index[0]][0].color) == COLOR
        assert tuple(back.ztraces["zt"].color) == COLOR
        # and again, from the series the first trip made
        again = _round_trip(back, tmp_path, "two")
    finally:
        back.close()
    try:
        assert tuple(again.palette_traces[again.palette_index[0]][0].color) == COLOR
        assert tuple(again.ztraces["zt"].color) == COLOR
    finally:
        again.close()

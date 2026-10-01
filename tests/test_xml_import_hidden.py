"""New from XML keeps a contour's `hidden` flag.

The section reader parses `hidden`, but `Trace.fromXMLObj` never copied it,
so every hidden contour came in shown, both from Reconstruct and from a
PyReconstruct XML export, which writes `hidden="true"`.
"""
from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.constants import blank_series

SECTION = """<?xml version="1.0"?>
<!DOCTYPE Section SYSTEM "section.dtd">
<Section index="0" thickness="0.05" alignLocked="false">
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Image mag="0.00254" contrast="1" brightness="0" red="true" green="true" blue="true" src="a.tif" />
<Contour name="domain1" hidden="false" closed="true" simplified="false" border="1 0 1" fill="1 0 1" mode="11"
 points="0 0, 1000 0, 1000 1000, 0 1000, "/>
</Transform>
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Contour name="shown" hidden="false" closed="true" simplified="false" border="1 0 0" fill="1 0 0" mode="9"
 points="0 0, 2 0, 2 2, 0 2, "/>
<Contour name="hidden" hidden="true" closed="true" simplified="false" border="0 1 0" fill="0 1 0" mode="9"
 points="3 3, 5 3, 5 5, 3 5, "/>
<Contour name="no_flag" closed="true" simplified="false" border="0 0 1" fill="0 0 1" mode="9"
 points="6 6, 8 6, 8 8, 6 8, "/>
</Transform>
</Section>"""


def test_hidden_contours_import_hidden(qapp, tmp_path):
    (tmp_path / "h.ser").write_text(
        blank_series.replace("[SECTION_NUM]", "0")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "0")
        .replace("[LASTTHUMBSECTION]", "0")
    )
    (tmp_path / "h.0").write_text(SECTION)

    series = xmlToJSON(str(tmp_path / "h.ser"))
    try:
        flags = {t.name: t.hidden for t in series.loadSection(0).tracesAsList()}
        palette = series.palette_traces[series.palette_index[0]]
        assert palette and not any(t.hidden for t in palette)
    finally:
        series.close()

    assert flags == {"shown": False, "hidden": True, "no_flag": False}
    assert all(type(v) is bool for v in flags.values())


def test_export_and_import_keep_hidden_traces_hidden(qapp, real_series, tmp_path):
    snum = max(
        real_series.sections,
        key=lambda n: len(real_series.loadSection(n).tracesAsList()),
    )
    section = real_series.loadSection(snum)
    traces = section.tracesAsList()
    assert len(traces) >= 2
    section.hideTraces(traces[::2], log_event=False)
    section.save()
    expected = sorted(
        (t.name, t.hidden) for t in real_series.loadSection(snum).tracesAsList()
    )
    assert any(h for _, h in expected) and not all(h for _, h in expected)

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))

    back = xmlToJSON(str(out / f"{real_series.name}.ser"))
    try:
        got = sorted((t.name, t.hidden) for t in back.loadSection(snum).tracesAsList())
    finally:
        back.close()

    assert got == expected

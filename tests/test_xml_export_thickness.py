"""Export to XML writes the section thickness in full.

`sectionJSONtoXML` wrote `str(round(section.thickness, 4))` for each section
and `seriesJSONtoXML` set the `.ser` `defaultThickness` to
`round(series.avg_thickness, 4)`, so `0.04787` went out as `0.0479` and a
series opened from the export kept the rounded value.
"""
import re

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)


@pytest.mark.parametrize(
    "thicknesses",
    [None, (0.05,), (0.04787,), (0.0469123,), (0.04787, 0.05123)],
    ids=["as-is", "0.05", "0.04787", "0.0469123", "mixed"],
)
def test_thickness_survives_export_and_import(qapp, real_series, tmp_path, thicknesses):
    if thicknesses is not None:
        for i, snum in enumerate(sorted(real_series.sections)):
            section = real_series.loadSection(snum)
            section.thickness = thicknesses[i % len(thicknesses)]
            section.save()
    expected = {n: real_series.loadSection(n).thickness for n in real_series.sections}
    average = sum(expected.values()) / len(expected)

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))

    for n, value in expected.items():
        text = (out / f"{real_series.name}.{n}").read_text()
        written = re.search(r'<Section[^>]*\bthickness="([^"]+)"', text).group(1)
        assert float(written) == value
    ser = (out / f"{real_series.name}.ser").read_text()
    written = re.search(r'\bdefaultThickness="([^"]+)"', ser).group(1)
    assert float(written) == pytest.approx(average, abs=1e-12)

    back = xmlToJSON(str(out / f"{real_series.name}.ser"))
    try:
        assert {n: back.loadSection(n).thickness for n in back.sections} == expected
    finally:
        back.close()

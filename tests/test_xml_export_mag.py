"""Export to XML writes the image magnification in full.

`sectionJSONtoXML` wrote `str(round(section.mag, 4))`, so the common
`0.00254` went out as `0.0025`, 1.6% off, and the images no longer lined up
with the traces in Reconstruct or after New from XML.
"""
import re

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)


@pytest.mark.parametrize("mag", [None, 0.00254, 0.0012345, 0.000045, 2])
def test_mag_survives_export_and_import(qapp, real_series, tmp_path, mag):
    if mag is not None:
        for snum in real_series.sections:
            section = real_series.loadSection(snum)
            section.mag = mag
            section.save()
    mags = {n: real_series.loadSection(n).mag for n in real_series.sections}

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))

    for n, expected in mags.items():
        text = (out / f"{real_series.name}.{n}").read_text()
        written = re.search(r'<Image[^>]*\bmag="([^"]+)"', text).group(1)
        assert float(written) == expected

    back = xmlToJSON(str(out / f"{real_series.name}.ser"))
    try:
        assert {n: back.loadSection(n).mag for n in back.sections} == mags
    finally:
        back.close()

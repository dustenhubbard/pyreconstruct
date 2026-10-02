"""Export to XML writes the `.ser` default thickness without float noise.

`seriesJSONtoXML` set `defaultThickness` to the plain float average of the
section thicknesses, and that average can carry noise, so sections that
alternate `0.045` and `0.049` wrote `defaultThickness="0.04700000000000001"`.
It is now written to twelve significant figures.
"""
import re

from PyReconstruct.modules.backend.func.xml_json_conversions import jsonToXML

THICKNESSES = (0.045, 0.049)


def test_default_thickness_is_written_without_float_noise(qapp, real_series, tmp_path):
    for i, snum in enumerate(sorted(real_series.sections)):
        section = real_series.loadSection(snum)
        section.thickness = THICKNESSES[i % len(THICKNESSES)]
        section.save()
    average = real_series.avg_thickness
    assert repr(average) == "0.04700000000000001"  # the plain average is noisy

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))

    ser = (out / f"{real_series.name}.ser").read_text()
    written = re.search(r'\bdefaultThickness="([^"]+)"', ser).group(1)
    assert written == "0.047"

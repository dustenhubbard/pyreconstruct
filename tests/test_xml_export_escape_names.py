"""Export to XML writes an image source or a palette name that holds `&` or `"`.

`sectionJSONtoXML` and the legacy branch of `Trace.getXMLObj` paste those
strings into template XML text that is parsed right after, and they pasted
them unescaped, so the parse raised `XMLSyntaxError` and the export stopped.
"""
import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.datatypes_legacy import (
    process_section_file,
    process_series_file,
)

NAMES = ["A&B.tif", 'A"B.tif', "A&amp;B <1>.tif"]


@pytest.mark.parametrize("src", NAMES)
def test_image_source_exports_and_imports_unchanged(qapp, real_series, tmp_path, src):
    snum = min(real_series.sections)
    section = real_series.loadSection(snum)
    section.src = src
    section.save()

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))
    name = real_series.name

    exported = process_section_file(str(out / f"{name}.{snum}"))
    assert exported.images[0].src == src

    back = xmlToJSON(str(out / f"{name}.ser"))
    try:
        assert back.loadSection(snum).src == src
    finally:
        back.close()


@pytest.mark.parametrize("trace_name", ["dendrite&spine", 'say"spine"', "a&amp;b"])
def test_palette_name_exports_and_imports_unchanged(qapp, real_series, tmp_path, trace_name):
    palette = real_series.palette_traces[real_series.palette_index[0]]
    palette[0].name = trace_name
    assert palette[0].name == trace_name  # no whitespace to normalize

    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(real_series, str(out))
    name = real_series.name

    exported = process_series_file(str(out / f"{name}.ser"))
    assert exported.contours[0].name == trace_name

    back = xmlToJSON(str(out / f"{name}.ser"))
    try:
        assert back.palette_traces[back.palette_index[0]][0].name == trace_name
    finally:
        back.close()

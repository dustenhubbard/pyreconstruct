"""PNG export reports invalid inputs and failed writes, then allows a retry."""

import pytest
from PIL import Image

from PyReconstruct.modules.backend.exports.svg_conversion import render_svg_to_png


@pytest.mark.parametrize("contents", ["not an SVG", '<svg xmlns="http://www.w3.org/2000/svg">'])
def test_invalid_svg_reports_an_error_and_allows_another_render(
    tmp_path, contents,
):
    svg = tmp_path / "section.svg"
    svg.write_text(contents, encoding="utf-8")
    png = tmp_path / "section.png"

    with pytest.raises(ValueError, match="could not read the exported SVG"):
        render_svg_to_png(svg, png)

    assert not png.exists()
    _write_svg(svg)
    render_svg_to_png(svg, png)
    with Image.open(png) as image:
        assert image.size == (4, 2)
        assert image.convert("RGBA").getpixel((2, 1)) == (25, 75, 125, 255)


def _write_svg(path):
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="2">'
        '<rect width="4" height="2" fill="#194b7d"/></svg>',
        encoding="utf-8",
    )


def test_png_write_failure_can_be_retried(tmp_path):
    svg = tmp_path / "section.svg"
    _write_svg(svg)
    png = tmp_path / "missing" / "section.png"

    with pytest.raises(OSError, match="could not write the PNG"):
        render_svg_to_png(svg, png)

    assert not png.exists()
    png.parent.mkdir()
    render_svg_to_png(svg, png, scale=0.5)
    with Image.open(png) as image:
        assert image.size == (2, 1)
        assert image.convert("RGBA").getpixel((1, 0)) == (25, 75, 125, 255)

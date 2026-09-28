import os
from pathlib import Path
from typing import Union
from tempfile import mkstemp
from io import BytesIO
import base64

from PyReconstruct.modules.calc import getImgDims, point_list_2_pix


def export_svg(section_data, svg_fp) -> Union[str, Path]:
    """Export untransformed section with traces as an svg.

    The traces are read from the section's columnar store
    (`section_data._columns`, live on every loaded section since the dual
    write went always-on) rather than from `section_data.contours` -- the
    first consumer flipped onto the store. The read is byte-identical to the
    object-model walk it replaces: `contourNamesInInsertionOrder()` is
    exactly `Section.contours`' contour order with emptied contours skipped
    (an emptied contour contributes no path either way), `ContourView`
    iterates a contour's rows in its `Contour.traces` list order, and every
    field read off a `TraceView` (`hidden`, `points`, `color`, `name`,
    `closed`) answers with the object model's own value.
    `tests/test_export_svg_png.py` pins the store walk against the object
    model on a section whose insertion order and sorted order disagree.
    """

    import svgwrite
    from svgwrite.extensions import Inkscape
    import zarr  # deferred: only needed for SVG/PNG export (pulls heavy I/O codecs)
    from PIL import Image

    ## Deferred like the imports above, but for a different reason: this
    ## module is imported by `datatypes/section.py` (for `Section.exportAsSVG`),
    ## so a module-level import of anything under `datatypes` would be
    ## circular during package initialization.
    from PyReconstruct.modules.datatypes.columnar_store import ContourView

    store = section_data._columns
    if store is None:
        ## Only a Section built through `Section.__new__` without `__init__`
        ## has no store; no production caller of this function has one.
        raise ValueError(
            f"section {section_data.n} has no columnar store to export from"
        )

    img_fp = section_data.src_fp
    mag = section_data.mag
    h, w = getImgDims(section_data.src_fp)

    ## Create drawing
    dwg = svgwrite.Drawing(
        svg_fp,
        profile="tiny",
        size=(w, h)
    )

    ## Add image layer and add image

    ## Convert img to base64-encoded string to embed in svg
    if "scale_" in str(img_fp):  # NOTE: Turn this into a utility
        
        z = zarr.open(str(img_fp))
        z_array = z[:]
        image = Image.fromarray(z_array)

        del z, z_array

    else:

        # PIL warns past MAX_IMAGE_PIXELS (about 89.5 million pixels) and
        # refuses an image past twice that (about 13377 x 13377) as a
        # decompression bomb, so a large section failed both SVG and PNG
        # export. This is the user's own section image, the same file
        # PyReconstruct already displays, so the guard is lifted for this one
        # open and put back after.
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        try:
            image = Image.open(img_fp)
            image.load()
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

    buffered = BytesIO()
    image.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode()

    # Create data URI
    image_data_uri = f"data:image/png;base64,{image_base64}"
            
    inkscape = Inkscape(dwg)
    image_layer = inkscape.layer(label="image", locked=False)

    image_layer.add(
        dwg.image(
            image_data_uri,
            insert=(0, 0),
            size=(w, h)
        )
    )

    ## Make trace layer and add traces
    trace_layer = inkscape.layer(label="traces", locked=False)

    for con_name in store.contourNamesInInsertionOrder():

        for trace in ContourView(store, con_name):

            if trace.hidden:  # don't render hidden traces
                continue

            ## `point_list_2_pix(points, mag, h)` is `Trace.asPixels`'
            ## whole body; `TraceView` deliberately carries no geometry
            ## methods, so the same function is called on the view's points.
            points = point_list_2_pix(trace.points, mag, h)
            color = svgwrite.rgb(*trace.color)

            path_data = "M " + " L ".join(f"{x},{y}" for x, y in points)

            if trace.closed: path_data = path_data + " Z"

            path_obj = dwg.path(
                d=path_data,
                id=trace.name,
                stroke=color,
                stroke_width=4,
                fill=color,
                fill_opacity=0.2
            )

            trace_layer.add(path_obj)

    ## Insert scale bar

    sb_length = 1  # microns 
    px_micron = 1 // mag
    
    sb_w = int(sb_length * px_micron)
    sb_h = int(sb_w * 0.2)

    color = svgwrite.rgb(0, 0, 0)  # black scale bar
    points = [(0, 0), (0, sb_h), (sb_w, sb_h), (sb_w, 0)]
    
    path_data = "M " + " L ".join(f"{x},{y}" for x, y in points) + " Z"

    path_obj = dwg.path(
                d=path_data,
                id="scale_bar",
                stroke=color,
                stroke_width=0,
                fill=color,
                fill_opacity=1.0
            )

    trace_layer.add(path_obj)

    ## Add layers to drawing
    dwg.add(image_layer)
    dwg.add(trace_layer)

    ## Save
    dwg.save()

    return svg_fp


def render_svg_to_png(svg_fp, png_fp, scale: float = 1.0):
    """Rasterize an SVG file to a PNG with QtSvg.

    The section image rides inside the SVG as a base64 PNG, and Qt's image
    reader refuses to decode any image over its allocation limit (256 MB by
    default, about 8192 x 8192 pixels). It logs a warning and draws the SVG
    without the image, so a large section came out as traces on a transparent
    background with no error. The limit is lifted for the render and put back
    after. The raster itself is sized by the caller's scale.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QImageReader, QPainter
    from PySide6.QtSvg import QSvgRenderer

    previous_limit = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(0)
    try:
        renderer = QSvgRenderer(str(svg_fp))
        if not renderer.isValid():
            raise ValueError(f"could not read the exported SVG: {svg_fp}")
        size = renderer.defaultSize()
        width = max(1, round(size.width() * scale))
        height = max(1, round(size.height() * scale))

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        renderer.render(painter)
        painter.end()
    finally:
        QImageReader.setAllocationLimit(previous_limit)

    if not image.save(str(png_fp), "PNG"):
        raise OSError(f"could not write the PNG: {png_fp}")
    return png_fp


def export_png(section_data, png_fp, scale: float=1.0):
    """Export untransformed section with traces as a png."""

    ## The descriptor is closed at once and the unlink rides a finally: the
    ## open fd leaked per export, and on Windows it also made the unlink
    ## raise PermissionError AFTER the png was written, so the user saw an
    ## error for an export that succeeded and the temp svg (with the whole
    ## embedded image) stayed behind (found 2026-08-28).
    fd, tmp_svg = mkstemp(suffix=".svg")
    os.close(fd)
    try:
        export_svg(section_data, tmp_svg)

        # Drawn with Qt's own SVG renderer rather than cairosvg. cairosvg
        # needs the native Cairo library, which no installer shipped, so PNG
        # export never worked from a packaged build (deferred 2026-08-07).
        # QtSvg is already in every build, needs no application object, and
        # matches cairosvg's output pixel for pixel at full size; only the
        # antialiased edges differ when scaled.
        render_svg_to_png(tmp_svg, png_fp, scale)
    finally:
        Path(tmp_svg).unlink(missing_ok=True)

    return png_fp

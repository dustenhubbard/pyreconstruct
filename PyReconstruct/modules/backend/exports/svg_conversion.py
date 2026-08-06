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

        image=Image.open(img_fp)

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


def export_png(section_data, png_fp, scale: float=1.0):
    """Export untransformed section with traces as a png."""

    _, tmp_svg = mkstemp(suffix=".svg")
    export_svg(section_data, tmp_svg)

    from cairosvg import svg2png

    svg2png(
        url=tmp_svg,
        write_to=png_fp,
        scale=scale
    )

    Path(tmp_svg).unlink()
    
    return png_fp

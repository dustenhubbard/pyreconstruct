"""ImageJ .roi file exporter."""

from pathlib import Path
from typing import Union, List, Tuple

from PyReconstruct.modules.backend.imports.mod_imports import modules_available
from PyReconstruct.modules.datatypes import Trace


coordinates = List[Tuple[float, float]]
filepath = Union[str, Path]


class RoiExporter:

    def __init__(self, trace: Trace, mag: float, img_height: int):

        ## Raise, never half-construct: returning early left the instance
        ## with no roi/coords, and the caller's next call crashed with an
        ## AttributeError right after the missing-package notice (found
        ## 2026-08-28). Callers check modules_available BEFORE building one.
        if not modules_available("roifile"):
            raise ModuleNotFoundError("roifile is required to export .roi files")

        import roifile
        self.roi_mod = roifile

        self.trace = trace
        self.coords = self.get_coords(mag, img_height)
        self.roi = self.get_roi()

    def export_roi(self, directory: filepath) -> Path:
        """Export an ImageJ .roi file to a directory.

        The filename dodges collisions with a numeric suffix: every trace in
        a contour carries the contour's name by construction, so naming the
        file from the trace name alone made a contour's N traces write the
        same file N times, and only the last survived while the user was
        told everything exported (found 2026-08-28).
        """

        if not isinstance(directory, Path):
            directory = Path(directory)

        output_fp = directory / f"{self.trace.name}-exported.roi"
        n = 1
        while output_fp.exists():
            n += 1
            output_fp = directory / f"{self.trace.name}-{n}-exported.roi"

        self.roi.tofile(output_fp)

        return output_fp

    def get_roi(self): 
        """Get an ImageJ roi object."""

        roi = self.roi_mod.ImagejRoi.frompoints(self.coords)
        
        roi.roitype = self.roi_mod.ROI_TYPE.POLYGON if self.trace.closed else self.roi_mod.ROI_TYPE.FREEHAND
        roi.name = self.trace.name

        return roi

    def get_coords(self, mag, img_height) -> coordinates:
        """Get coordinates as pixels."""

        coords = self.trace.asPixels(mag, img_height, subpix=True)

        return [
            (round(x, 3), round(y, 3)) for x, y in coords
        ]


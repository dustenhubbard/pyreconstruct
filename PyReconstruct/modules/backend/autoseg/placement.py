"""Where a Zarr labels array sits in the field.

One calculation for the label overlay and the label import. It works on
metadata the callers have already read (sizes and offsets in nm, from
``get_label_resolutions`` and ``get_label_offset``) and touches neither zarr
nor Qt.

Both callers share the magnification, the crop origin and the label offsets in
label pixels. They anchor rows and pick a section's slice each their own way,
so each has its own entry: ``to_field`` and ``slice_index`` for the import,
``overlay_origin`` for the overlay.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LabelPlacement:
    """A labels array placed in the field.

    Label columns count right from the left edge and rows count down from the
    top, as the array stores them. Field y counts up.
    """

    mag: float  # µm per label pixel
    overlay_mag: float  # the same, multiplied in the overlay's order
    window_x: float  # raw's left edge in the field
    window_y: float  # raw's bottom edge in the field
    col_shift: float  # the labels' x offset from raw, in label pixels
    row_shift: float  # the labels' y offset from raw, in label pixels
    slice_shift: float  # the labels' z offset from raw, in label slices
    raw_rows: float  # raw's height in label rows
    sections: tuple  # raw's section numbers, one per raw slice

    def to_field(self, points):
        """Label (column, row) points as field (x, y) points, for the import.

        Rows are flipped around raw's height.

        Params:
            points (array): n by 2 label coordinates; a pixel's top left
                corner is its column and row
        Returns:
            (np.ndarray) n by 2 field coordinates, before any transform
        """
        pts = np.array(points, dtype=np.float64)
        pts[:, 0] += self.col_shift
        pts[:, 1] += self.row_shift
        pts[:, 1] *= -1
        pts[:, 1] += self.raw_rows
        pts *= self.mag
        pts[:, 0] += self.window_x
        pts[:, 1] += self.window_y
        return pts

    def slice_index(self, snum):
        """The label slice the import reads for a section, or None.

        Raw's slices are its sections in order. None for a section outside
        raw's sections or below the labels; the high end is the caller's to
        check.
        """
        if snum not in self.sections:
            return None
        zi = self.sections.index(snum) - round(self.slice_shift)
        return zi if zi >= 0 else None

    def overlay_origin(self):
        """The overlay's field x and y and its first section.

        The overlay hangs its rows from y and shows slice
        ``round(section - first section)``.
        """
        x = self.window_x + self.col_shift * self.overlay_mag
        y = self.window_y + self.row_shift * self.overlay_mag
        s = self.sections[0] + self.slice_shift
        return x, y, s


def label_placement(resolution, raw_resolution, offset, window, sections, true_mag, raw_height):
    """Place a labels array over the raw it was made from.

    Params:
        resolution (list): the labels' (z, y, x) voxel size in nm
        raw_resolution (list): raw's (z, y, x) voxel size in nm
        offset (list): the labels' (z, y, x) offset from raw in nm
        window (list): raw's field window; x and y are its bottom left corner
        sections (list): raw's section numbers, one per raw slice
        true_mag (float): µm per raw pixel
        raw_height (int): raw's height in raw pixels
    Returns:
        (LabelPlacement) where the labels sit
    """
    return LabelPlacement(
        mag=true_mag / raw_resolution[-1] * resolution[-1],
        overlay_mag=true_mag * (resolution[-1] / raw_resolution[-1]),
        window_x=window[0],
        window_y=window[1],
        col_shift=offset[2] / resolution[2],
        row_shift=offset[1] / resolution[1],
        slice_shift=offset[0] / resolution[0],
        raw_rows=raw_height * (raw_resolution[1] / resolution[1]),
        sections=tuple(sections),
    )

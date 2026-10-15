"""Where a Zarr labels array sits in the field.

One calculation for the label overlay and the label import, so a label pixel
is drawn where its imported trace lands. It works on metadata the callers have
already read (sizes and offsets in nm, from ``get_label_resolutions`` and
``get_label_offset``) and touches neither zarr nor Qt.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LabelPlacement:
    """A labels array placed in the field, in label pixels.

    Label columns count right from the left edge and rows count down from the
    top, as the array stores them. Field y counts up, so rows are flipped
    around raw's height.
    """

    mag: float  # µm per label pixel
    window_x: float  # raw's left edge in the field
    window_y: float  # raw's bottom edge in the field
    col_shift: float  # label columns between raw's left edge and the labels'
    row_shift: float  # label rows between raw's top edge and the labels'
    raw_rows: float  # raw's height in label rows
    sections: tuple  # raw's section numbers, one per raw slice
    z_offset: int  # raw slices before the first label slice

    def to_field(self, points):
        """Label (column, row) points as field (x, y) points.

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

    def to_label(self, x, y):
        """The label (column, row) at a field point, as floats (see to_field)."""
        col = (x - self.window_x) / self.mag - self.col_shift
        row = self.raw_rows - (y - self.window_y) / self.mag - self.row_shift
        return col, row

    def slice_index(self, snum):
        """The label slice shown on a section, or None if there is none.

        Raw's slices are its sections in order, so a gap in the section
        numbers is not a slice. The high end is the caller's to check.
        """
        if snum not in self.sections:
            return None
        zi = self.sections.index(snum) - self.z_offset
        return zi if zi >= 0 else None


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
        window_x=window[0],
        window_y=window[1],
        col_shift=offset[2] / resolution[2],
        row_shift=offset[1] / resolution[1],
        raw_rows=raw_height * (raw_resolution[1] / resolution[1]),
        sections=tuple(sections),
        z_offset=round(offset[0] / resolution[0]),
    )

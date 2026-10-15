import os
import zarr
import numpy as np

from PySide6.QtCore import (
    Qt
)
from PySide6.QtGui import (
    QPixmap, 
    QImage, 
    QPainter, 
)
os.environ['QT_IMAGEIO_MAXALLOC'] = "0"  # disable max image size

from PyReconstruct.modules.datatypes import (
    Series,
    Section
)

class ZarrLayer():

    def __init__(self, series : Series):
        """Create the image field.

            Params:
                section (Section): the section object for the field
                series (Series): the series object
        """
        self.series = series
        if self.series.zarr_overlay_fp:
            self.loadZarrData()
        else:
            self.zarr = None

    def loadZarrData(self):
        """Load the relevant data from the zarr file."""
        # here, not at the top: conversions imports this package
        from PyReconstruct.modules.backend.autoseg.conversions import (
            get_label_offset,
            get_label_resolutions,
            get_true_mag,
            is_label_array,
            label_volume,
        )

        group = zarr.open(self.series.zarr_overlay_fp)
        overlay = group[self.series.zarr_overlay_group]
        raw = group["raw"]
        # sizes and offsets in nm, whatever units each array declares. An
        # array with no size gets the grid label import gives it: raw the
        # series grid, labels raw's grid
        self.resolution, self.raw_resolution = get_label_resolutions(
            overlay, raw, self.series
        )

        # labels are read as (z, y, x), so a (1, z, y, x) label array is
        # its one channel; an image keeps its channels
        self.is_labels = is_label_array(overlay)
        self.zarr = label_volume(overlay) if self.is_labels else overlay

        # get relevant data from overlay zarr
        self.offset = get_label_offset(overlay, raw)

        # get the relevant data from the raw in the zarr folder
        self.zarr_x, self.zarr_y = tuple(raw.attrs["window"][:2])
        self.zarr_s = raw.attrs["sections"][0]
        self.zarr_mag = get_true_mag(raw) * (self.resolution[-1] / self.raw_resolution[-1])

        # modify attributes
        pixel_offset = [o / r for o, r in zip(self.offset, self.resolution)]
        field_offset = [p * self.zarr_mag for p in pixel_offset]
        self.zarr_x += field_offset[2]
        self.zarr_y += field_offset[1]
        self.zarr_s += pixel_offset[0]

        # defaults
        self.selected_ids = []

        # load colors
        if self.is_labels:
            self.id_colors = {}
    
    def _screenGrid(self, pixmap_dim, window, bh):
        """Map the screen onto zarr pixel coordinates.

            Params:
                pixmap_dim (tuple): the w and h of the screen in pixels
                window (list): the x, y, w, and h of the field window
                bh (int): the zarr height in pixels (rows count down from its top)
            Returns:
                (tuple) the zarr x and y at the screen's top left corner and the
                screen pixels per zarr pixel in x and y, or None for an empty view
        """
        pixmap_w, pixmap_h = tuple(pixmap_dim)
        window_x, window_y, window_w, window_h = tuple(window)
        if pixmap_w <= 0 or pixmap_h <= 0 or window_w <= 0 or window_h <= 0:
            return None
        wxmin = (window_x - self.zarr_x) / self.zarr_mag
        wymin = bh - (window_y + window_h - self.zarr_y) / self.zarr_mag
        sx = pixmap_w * self.zarr_mag / window_w
        sy = pixmap_h * self.zarr_mag / window_h
        return wxmin, wymin, sx, sy

    def getID(self, pix_x : int, pix_y : int):
        """Get the ID drawn at a screen pixel.

        The coordinates name a screen pixel the way a mouse event does, by its
        top left corner. The ID is read at the pixel's center through
        _zarrIndex, which generateZarrLayer also uses to pick the label it
        draws there, so the two always agree.

            Params:
                pix_x (int): the x coord in screen pixels
                pix_y (int): the y coord in screen pixels
        """
        if not self.is_labels:
            return None
        
        # check if the section is within the range
        bz, bh, bw = self.zarr.shape
        z = round(self.section.n - self.zarr_s)
        if not 0 <= z < bz:
            return None
        
        # the zarr pixel under the screen pixel's center, by the same mapping
        # generateZarrLayer draws with
        grid = self._screenGrid(self.pixmap_dim, self.series.window, bh)
        if grid is None:
            return None
        wxmin, wymin, sx, sy = grid
        image_x = int(_zarrIndex(pix_x, wxmin, sx))
        image_y = int(_zarrIndex(pix_y, wymin, sy))

        if not 0 <= image_x < bw:
            return None
        if not 0 <= image_y < bh:
            return None

        return self.zarr[z, image_y, image_x]

    def selectID(self, pix_x : int, pix_y : int):
        """Select the ID at a given screen pixel (see getID).
        
            Params: 
                pix_x (int): the x coord in screen pixels
                pix_y (int): the y coord in screen pixels
        """
        label_id = self.getID(pix_x, pix_y)
        if label_id:
            if label_id in self.selected_ids:
                self.selected_ids.remove(label_id)
            else:
                self.selected_ids.append(label_id)
            return True
        return False

    def getPresentIds(self):
        """Return the label ids visible on the current section.

        These are the unique non-zero ids in the current section's slice of the
        label overlay -- i.e. the labels the user actually sees colored (the
        whole crop is colored, not just ``selected_ids``). Used to tie the
        shuffle-colors guarantee to what is on screen. Returns an empty list
        when this is not a label overlay or the current section falls outside
        the overlay's z-range.
        """
        if not self.is_labels:
            return []
        bz = self.zarr.shape[0]
        z = round(self.section.n - self.zarr_s)
        if not 0 <= z < bz:
            return []
        present = np.unique(self.zarr[z])
        return [int(v) for v in present.tolist() if v != 0]

    def deselectAll(self):
        """Deselect all the IDs."""
        self.selected_ids = []
    
    def mergeLabels(self):
        """Merge the selected labels."""
        if not (self.is_labels and len(self.selected_ids) > 1):
            return
        
        min_id = min(self.selected_ids)
        self.selected_ids.remove(min_id)     

        for z in range(self.zarr.shape[0]):
            section = self.zarr[z]
            for label_id in self.selected_ids:
                section[section == label_id] = min_id
                self.zarr[z] = section        
        self.selected_ids = [min_id]
    
    def generateZarrLayer(self, section : Section, pixmap_dim : tuple, window : list) -> QPixmap:
        """Generate the zarr layer.
        
            Params:
                section (Section): the current section object
                pixmap_dim (tuple): the w and h of the main window
                window (list): the x, y, w, and h of the field window
            Returns:
                zarr_layer (QPixmap): the zarr layer
        """
        self.section = section

        # return nothing if there is no zarr file
        if not self.zarr:
            return None
        
        if self.is_labels:
            bz, bh, bw = self.zarr.shape
        else:
            bz, bh, bw = self.zarr.shape[1:]
        
        # check if the section is within the range
        z = round(section.n - self.zarr_s)
        if not 0 <= z < bz:
            return None
        
        # save and unpack window and pixmap values
        self.pixmap_dim = pixmap_dim
        self.series.window = window
        pixmap_w, pixmap_h = tuple(pixmap_dim)

        # the zarr pixel under each screen pixel's center, one index per
        # screen column and one per screen row (see _zarrIndex)
        grid = self._screenGrid(pixmap_dim, window, bh)
        if grid is None:
            return None
        wxmin, wymin, sx, sy = grid
        self.zarr_scaling = sx
        cols = _zarrIndex(np.arange(pixmap_w), wxmin, sx)
        rows = _zarrIndex(np.arange(pixmap_h), wymin, sy)

        # the screen columns and rows that land inside the zarr; the indices
        # only grow across the screen, so each is one contiguous run
        in_x = np.flatnonzero((cols >= 0) & (cols < bw))
        in_y = np.flatnonzero((rows >= 0) & (rows < bh))
        # return nothing if the requested view is completely out of bounds
        if in_x.size == 0 or in_y.size == 0:
            return None
        x0, x1 = int(in_x[0]), int(in_x[-1]) + 1
        y0, y1 = int(in_y[0]), int(in_y[-1]) + 1
        cols = cols[x0:x1]
        rows = rows[y0:y1]

        # read the zarr pixels under the visible part of the screen; they are
        # repeated or skipped below so there is exactly one per screen pixel
        c0, c1 = int(cols[0]), int(cols[-1]) + 1
        r0, r1 = int(rows[0]), int(rows[-1]) + 1
        rows = rows - r0
        cols = cols - c0
        w, h = x1 - x0, y1 - y0

        def toScreen(a):
            """Pick a crop-shaped array's entry for each screen pixel."""
            return np.take(np.take(a, rows, axis=0), cols, axis=1)

        if self.is_labels:
            crop = self.zarr[z, r0:r1, c0:c1]
            # color each label the way autoseg import colors its trace, so the
            # overlay preview matches the imported objects exactly. id 0 is
            # background (not a segment); keep it the neutral gray the previous
            # colorize(0) produced so the overlay background is unchanged.
            # Imported locally: the autoseg package imports conversions, which
            # imports backend.view -- a module-level import here would form a
            # circular import while backend.view is still initializing.
            from PyReconstruct.modules.backend.autoseg.palette import (
                palette_color_array,
            )
            palette = self.series.getOption("autoseg_color_palette") or None
            seed = self.series.getOption("autoseg_color_seed") or 0
            # zoomed in, the crop is the smaller array, so color it and then
            # repeat the colors; zoomed out, pick the screen's labels first
            color_first = crop.size <= w * h
            ids = crop if color_first else toScreen(crop)
            colors = palette_color_array(
                ids, palette, seed, background=(100, 100, 100)
            )
            if color_first:
                colors = toScreen(colors)
            screen_colors = np.ascontiguousarray(colors, dtype=np.uint8)
            im_screen = QImage(
                screen_colors.data,
                w,
                h,
                screen_colors.strides[0],
                QImage.Format.Format_RGB888
            )
            # generate overlay for selected labels
            if self.selected_ids:
                selected = np.where(
                    np.isin(ids, self.selected_ids), 255, 0
                ).astype(np.uint8)
                if color_first:
                    selected = toScreen(selected)
                screen_selected = np.ascontiguousarray(selected)
                im_screen_selected = QImage(
                    screen_selected.data,
                    w,
                    h,
                    screen_selected.strides[0],
                    QImage.Format.Format_Grayscale8
                )
                painter = QPainter(im_screen)
                painter.setOpacity(0.5)
                painter.drawImage(0, 0, im_screen_selected)
                painter.end()
        else:
            crop = np.moveaxis(self.zarr[:3, z, r0:r1, c0:c1], 0, -1)
            screen_colors = np.ascontiguousarray(toScreen(crop), dtype=np.uint8)
            im_screen = QImage(
                screen_colors.data,
                w,
                h,
                screen_colors.strides[0],
                QImage.Format.Format_RGB888
            )

        # one image pixel per screen pixel, so Qt does no scaling or sampling
        zarr_layer = QPixmap(pixmap_w, pixmap_h)
        zarr_layer.fill(Qt.transparent)
        painter = QPainter(zarr_layer)
        painter.drawImage(x0, y0, im_screen)
        painter.end()

        return zarr_layer


def _zarrIndex(pix, start, scale):
    """The zarr pixel index under the center of a screen pixel.

    Shared by getID and generateZarrLayer, so what is picked is always what is
    drawn. Works on one index or on an array of them.

        Params:
            pix (int or array): the screen pixel index (column or row)
            start (float): the zarr coordinate at the screen's edge
            scale (float): screen pixels per zarr pixel
        Returns:
            (int or array) the zarr pixel index, which may be out of range
    """
    return np.floor(start + (np.asarray(pix) + 0.5) / scale).astype(np.int64)

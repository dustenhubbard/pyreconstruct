import os
import math

import zarr
import numpy as np

from PySide6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QRect
)
from PySide6.QtGui import (
    QPixmap, 
    QImage, 
    QPen, 
    QColor, 
    QPainter, 
    QPolygon
)
os.environ['QT_IMAGEIO_MAXALLOC'] = "0"  # disable max image size

from PyReconstruct.modules.datatypes import (
    Series,
    Section,
    Transform
)
from PyReconstruct.modules.calc import fieldPointToPixmap

class ImageLayer():

    def __init__(self, section : Section, series : Series):
        """Create the image field.

            Params:
                section (Section): the section object for the field
                series (Series): the series object
        """
        self.section = section
        self.series = series
        self.loadImage()
    
    def loadImage(self):
        """Load the image."""
        # get the image path
        self.is_zarr_file = self.series.src_dir.endswith("zarr")
        
        # if the image folder is a zarr file
        if self.is_zarr_file:
            if os.path.isdir(self.series.src_dir):
                self.zg = zarr.open(self.series.src_dir)
                # special expection: zarr is in previous format
                if self.section.src in self.zg:
                    # reorganize the zarr file (move images into scale_1 folder)
                    self.zg.create_group("scale_1", overwrite=True)
                    for g in self.zg:
                        if g != "scale_1":
                            self.zg.move(g, os.path.join("scale_1", g))
                # gather scales
                self.scales = self.section.zarr_scales
                if not self.scales:
                    self.image_found = False
                else:
                    self.image_found = True
                    self.scales.sort(reverse=True)
                    self.is_scaled = self.scales != [1]
                    self.selected_scale = self.scales[-1]
            else:
                self.image_found = False
            if self.image_found:
                self.image = self.zg[f"scale_{self.selected_scale}"][self.section.src]
                self.bh, self.bw = (n * self.selected_scale for n in self.image.shape)
                self.base_corners = [(0, 0), (0, self.bh), (self.bw, self.bh), (self.bw, 0)]
                self.image_found = True
        
        # if saved as normal images
        else:
            src_path = self.section.src_fp
            self.image = QImage(src_path)
            if self.image.isNull():
                self.image_found = False
            else:
                self.bw, self.bh = self.image.width(), self.image.height()
                self.base_corners = [(0, 0), (0, self.bh), (self.bw, self.bh), (self.bw, 0)]
                self.image_found = True
    
    def _calcTformCorners(self, base_pixmap : QPixmap, tform : Transform) -> tuple:
        """Calculate the vector for each corner of a transformed image.
        
            Params:
                base_pixmap (QPixmap): untransformed image
                tform (QTransform): transform to apply to the image
            Returns:
                (tuple) the four corners (starting from bottom left moving clockwise)
        """
        base_coords = base_pixmap.size() # base image dimensions
        height_vector = tform.map(0, base_coords.height()) # create a vector for base height and transform
        width_vector = tform.map(base_coords.width(), 0) # create a vector for base width and transform
        # calculate coordinates for the top left corner of image
        if height_vector[0] < 0:
            tl_x = -height_vector[0]
        else:
            tl_x = 0
        if width_vector[1] < 0:
            tl_y = -width_vector[1]
        else:
            tl_y = 0
        tl = (tl_x, tl_y)
        # calculate coordinates for the bottom left corner of the image
        bl_x = tl_x + height_vector[0]
        bl_y = tl_y + height_vector[1]
        bl = (bl_x, bl_y)
        # calculate coordinates for top right corner of the image
        tr_x = tl_x + width_vector[0]
        tr_y = tl_y + width_vector[1]
        tr = (tr_x, tr_y)
        # calculate coordinates for bottom right corner of the image
        br_x = bl_x + width_vector[0]
        br_y = bl_y + width_vector[1]
        br = (br_x, br_y)

        return bl, tl, tr, br
    
    def _drawBrightness(self, image_layer):
        """Draw the brightness on the image field.

            Params:
                image_layer (QImage): the image to draw brightness on
        """
        # paint to image
        painter = QPainter(image_layer)
        b = self.section.brightness / 100
        # different modes for high and low brightness
        painter.setBrush(Qt.white if b >= 0 else Qt.black)
        painter.setOpacity(abs(b))
        painter.drawPolygon(self.bc_poly)
        painter.end()
    
    def _drawContrast(self, image_layer):
        """Draw the contrast on the image field.

            Params:
                image_layer (QImage): the image to draw contrast on
        """
        painter = QPainter(image_layer)

        if self.section.contrast >= 0:
            overlays = self.section.contrast / 20
            # overlay image on itself for added contrast
            painter.setCompositionMode(QPainter.CompositionMode_Overlay)
            # draw the images n (int) times on itself
            for _ in range(int(overlays)):
                painter.drawImage(0, 0, image_layer)
            # draw another transparent image
            opacity = overlays % 1
            if opacity > 0:
                painter.setOpacity(opacity)
                painter.drawImage(0, 0, image_layer)
        else:
            # overlay gray on image for decreased contrast
            opacity = abs(self.section.contrast) / 100
            painter.setOpacity(opacity)
            gray = QColor(128, 128, 128)
            painter.setPen(QPen(gray, 0))
            painter.setBrush(gray)
            painter.drawPolygon(self.bc_poly)
        painter.end()

    def generateImageLayer(self, pixmap_dim : tuple, window : list, get_crop_only=False, bc=True) -> QPixmap:
        """Generate the image layer as a pixmap.

        QPixmap is GUI-thread-only: call this from the GUI thread.
        Worker threads should use generateImageArray/_generateImage instead.

            Params:
                pixmap_dim (tuple): the w and h of the main window
                window (list): the x, y, w, and h of the field window
                get_crop_only (bool): returns only the direct crop from the image (only for use with brightness/contrast functions)
            Returns:
                image_layer (QPixmap): the image layer
        """
        return QPixmap.fromImage(
            self._generateImage(pixmap_dim, window, get_crop_only, bc)
        )

    def _generateImage(self, pixmap_dim : tuple, window : list, get_crop_only=False, bc=True) -> QImage:
        """Generate the image layer as a QImage.

        Unlike QPixmap, QImage is safe to create and paint on outside
        the GUI thread, so this can run on QThreadPool workers.

            Params:
                pixmap_dim (tuple): the w and h of the main window
                window (list): the x, y, w, and h of the field window
                get_crop_only (bool): returns only the direct crop from the image (only for use with brightness/contrast functions)
            Returns:
                image_layer (QImage): the image layer
        """
        # set attrs
        self.series.window = window
        self.pixmap_dim = pixmap_dim

        # return blank if image was not found
        if not self.image_found:
            blank_image = QImage(*pixmap_dim, QImage.Format.Format_ARGB32_Premultiplied)
            blank_image.fill(Qt.black)
            return blank_image

        # setup
        tform = self.section.tform
        mag = self.section.mag
        wx, wy, ww, wh = tuple(self.series.window)
        pmw, pmh = tuple(self.pixmap_dim)
        iw, ih = self.bw, self.bh
        s = self.scaling = pmw / (ww / mag)

        # step 0: get the applicable zarr scale if using zarr file for images
        if self.is_zarr_file:
            scale_level = self.scales[-1]
            for scale in self.scales[:-1]:
                if (1/self.scaling) > scale:
                    scale_level = scale
                    break
            if self.selected_scale != scale_level:
                self.image = self.zg[f"scale_{scale_level}"][self.section.src]
                self.selected_scale = scale_level
        else:
            scale_level = 1
        

        # step 1: get the polygon for the window
        poly_window = [
            (wx, wy),
            (wx, wy + wh),
            (wx + ww, wy + wh),
            (wx + ww, wy)
        ]

        # step 2: untransform the window poly
        utf_poly_window = tform.map(poly_window, inverted=True)

        # step 3: convert to pixel coordinates
        utf_pixel_poly_window = [(x / mag, y / mag) for x, y in utf_poly_window]

        # step 4: get bounds to crop image
        bounds = getBounds(utf_pixel_poly_window)

        # step 5: adjust bounds to image dimensions and get necessary filling
        bounds, filling = adjustBounds(bounds, iw, ih)
        # check if completely out of bounds
        if bounds is None:
            blank_image = QImage(pmw, pmh, QImage.Format.Format_ARGB32_Premultiplied)
            blank_image.fill(Qt.black)
            return blank_image
        # unpack values otherwise
        fxmin, fymin, fxmax, fymax = bounds        # floats: see adjustBounds
        xminp, yminp, xmaxp, ymaxp = filling

        # Step 6: crop OUTWARD to whole pixels (floor the mins, ceil the
        # maxes), so the crop always covers the window's float span. The old
        # round() could shrink it by a pixel, which scaled to a multi-pixel
        # shortfall and painted the deficit black at the field's edge -- the
        # intermittent 1px line parked 2026-08-26, root-caused by the review
        # fleet (3029 of 4000 views showed it).
        if self.is_zarr_file:
            zh_total, zw_total = self.image.shape
            zx0 = max(0, math.floor(fxmin / scale_level))
            zy0 = max(0, math.floor(fymin / scale_level))
            zx1 = min(zw_total, math.ceil(fxmax / scale_level))
            zy1 = min(zh_total, math.ceil(fymax / scale_level))
            # Dimensions come from the SLICE, never re-derived by rounding
            # the full-resolution bounds: the pyramid levels are written by
            # iterated halving, so round(full/scale) disagrees with the
            # stored size for many images, and a QImage declared bigger than
            # its buffer reads past the numpy allocation (found 2026-08-28).
            zarr_saved = self.image[zh_total - zy1: zh_total - zy0, zx0:zx1]
            zh, zw = zarr_saved.shape
            im_crop = QImage(
                zarr_saved.data,
                zw,
                zh,
                zarr_saved.strides[0],
                QImage.Format.Format_Grayscale8
            )
            # the crop's full-resolution footprint, for placement below
            cx0, cy1 = zx0 * scale_level, zy1 * scale_level
            crop_w_full = zw * scale_level
            crop_h_full = zh * scale_level
        else:
            cx0 = max(0, math.floor(fxmin))
            cy0 = max(0, math.floor(fymin))
            cx1 = min(iw, math.ceil(fxmax))
            cy1 = min(ih, math.ceil(fymax))
            im_crop = self.image.copy(QRect(cx0, ih - cy1, cx1 - cx0, cy1 - cy0))
            crop_w_full = cx1 - cx0
            crop_h_full = cy1 - cy0

        if get_crop_only:  # only for use with brightness/contrast functions
            # copy so the returned image owns its data (the zarr crop wraps
            # a local numpy buffer that dies with this scope)
            return im_crop.copy() if self.is_zarr_file else im_crop

        # step 7: scale the cropped image (ceil: never come up short)
        im_scaled = im_crop.scaled(
            math.ceil(crop_w_full * s),
            math.ceil(crop_h_full * s)
        )

        # Step 8: fill the image. The canvas spans exactly the window
        # (filling included), and the scaled crop is placed by its exact
        # fractional offset from the window edge -- the outward margins from
        # the floor/ceil above hang off the canvas instead of shifting the
        # content. With an identity transform this canvas IS pixmap-sized,
        # so the rip below is exact.
        im_filled = QImage(
            round((xminp + (fxmax - fxmin) + xmaxp) * s),
            round((ymaxp + (fymax - fymin) + yminp) * s),
            QImage.Format.Format_ARGB32_Premultiplied
        )
        im_filled.fill(Qt.black)
        painter = QPainter(im_filled)
        painter.drawImage(
            QPointF(
                (xminp - (fxmin - cx0)) * s,
                (ymaxp - (cy1 - fymax)) * s,
            ),
            im_scaled
        )
        painter.end()

        # step 9: transform the filled image
        im_tformed = im_filled.transformed(
            tform.imageTransform().getQTransform()
        )

        # Step 10: rip the visible region from the transformed image. The
        # origin is clamped at zero: a negative origin makes QImage.copy
        # invent black source columns, which was the other half of the edge
        # line (see step 7).
        im_ripped = im_tformed.copy(
            max(0, round((im_tformed.width() - pmw) / 2)),
            max(0, round((im_tformed.height() - pmh) / 2)),
            pmw,
            pmh
        )

        # Step 11: add blank space to account for rounding errors. CENTERED,
        # not anchored top-left: anchoring pushed the whole shortfall onto
        # the right and bottom edges as a visible black line.
        if (im_ripped.width(), im_ripped.height()) != pixmap_dim:
            image_layer = QImage(*pixmap_dim, QImage.Format.Format_ARGB32_Premultiplied)
            image_layer.fill(Qt.black)
            painter = QPainter(image_layer)
            painter.drawImage(
                (pmw - im_ripped.width()) // 2,
                (pmh - im_ripped.height()) // 2,
                im_ripped
            )
            painter.end()
        else:
            image_layer = im_ripped
        
        # step 12: draw brightness and contrast
        # create the brightness/contrast polygon (draws as a polygon over the image)
        if bc:
            self.bc_poly = QPolygon()
            for x, y in self.base_corners:
                x, y = (x * mag, y * mag)
                x, y = tform.map(x, y)
                x, y = fieldPointToPixmap(x, y, self.series.window, self.pixmap_dim, self.section.mag)
                self.bc_poly.append(QPoint(x, y))
            self._drawBrightness(image_layer)
            self._drawContrast(image_layer)

        return image_layer
    
    def generateImageArray(self, pixmap_dim : tuple, window : list, get_crop_only=False, bc : bool = True):
        """Generate the image layer.
        
            Params:
                pixmap_dim (tuple): the w and h of the 2D array
                window (list): the x, y, w, and h of the field window
            Returns:
                (numpy.ndarray) the image as a numpy array
        """
        # generate the qimage directly (no QPixmap: safe off the GUI thread)
        qimage = self._generateImage(
            pixmap_dim,
            window,
            get_crop_only,
            bc
        )
        qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)

        # convert the qimage to a numpy array
        width = qimage.width()
        height = qimage.height()
        raw = np.frombuffer(qimage.bits(), np.uint8)
        raw = raw.reshape((height, width, 4))[:,:,0]
        arr = np.array(raw, dtype=np.uint8)

        return arr

def getBounds(points : list):
    """Get the bounding rectangle and shift in origin for a set of points.
    
            Params:
                points (list): a list of points
            Returns:
                (tuple): xmin, ymin, xmax, ymax
    """
    xmin = points[1][0]
    xmax = points[1][0]
    ymin = points[1][1]
    ymax = points[1][1]
    for point in points:
        x, y = point
        if x < xmin:
            xmin = x
        if x > xmax: xmax = x
        if y < ymin:
            ymin = y
        if y > ymax: ymax = y
    
    return xmin, ymin, xmax, ymax

def adjustBounds(bounds, w, h):
    """Adjust the bounds to a specific width and height."""
    xmin, ymin, xmax, ymax = tuple(bounds)

    if xmin > w:
        return None, None
    elif xmin < 0:
        xmin_filling = 0 - xmin
        xmin = 0
    else:
        xmin_filling = 0
    
    if ymin > h:
        return None, None
    elif ymin < 0:
        ymin_filling = 0 - ymin
        ymin = 0
    else:
        ymin_filling = 0
    
    if xmax < 0:
        return None, None
    elif xmax > w:
        xmax_filling = xmax - w
        xmax = w
    else:
        xmax_filling = 0
    
    if ymax < 0:
        return None, None
    elif ymax > h:
        ymax_filling = ymax - h
        ymax = h
    else:
        ymax_filling = 0

    ## FLOATS, deliberately. This used to round, and the rounding was the
    ## root of the parked 1px edge line: a crop rounded up to a whole image
    ## pixel scales to less than the pixmap, and the pipeline paints the
    ## deficit black. The caller floors/ceils for the actual crop rect and
    ## places the result by the exact fractional offsets (found 2026-08-28).
    return (
        (xmin, ymin, xmax, ymax),
        (xmin_filling, ymin_filling, xmax_filling, ymax_filling)
    )

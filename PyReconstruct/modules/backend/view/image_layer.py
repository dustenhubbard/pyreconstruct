import os
import math

import zarr
import numpy as np

from PySide6.QtCore import (
    Qt,
    QPoint,
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
from .zarr_layer import _zarrIndex

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
                loaded = self.image
                # the crop the brightness and contrast optimizer reads
                self.image = _sampleableImage(loaded)
                self.bw, self.bh = self.image.width(), self.image.height()
                self.base_corners = [(0, 0), (0, self.bh), (self.bw, self.bh), (self.bw, 0)]
                self.image_found = True
                # what _sampleWindow draws from, read in place with no
                # per-view copy; the same image unless alpha has to be
                # premultiplied at full depth first
                self._draw_image = _drawableImage(loaded, self.image)
                self._pixels = _PixelView(self._draw_image)
    
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
        pmw, pmh = tuple(self.pixmap_dim)

        # return blank if image was not found
        if not self.image_found:
            return _blank(pmw, pmh)

        # setup
        tform = self.section.tform
        mag = self.section.mag
        wx, wy, ww, wh = tuple(self.series.window)
        self.scaling = pmw / (ww / mag)

        # get the applicable zarr scale if using zarr file for images
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

        if get_crop_only:  # only for use with brightness/contrast functions
            return self._cropWindow(tform, mag, scale_level)

        if pmw <= 0 or pmh <= 0 or ww <= 0 or wh <= 0:
            return _blank(pmw, pmh)

        image_layer = self._sampleWindow(pmw, pmh, tform, mag, scale_level)

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
    
    def _sampleWindow(self, pmw : int, pmh : int, tform : Transform, mag : float, scale_level : int) -> QImage:
        """Draw the image by reading the source pixel under each screen pixel's center.

        Each screen pixel center is taken to field coordinates, through the
        inverse transform, and floored to an image pixel. That is the geometry
        traces are drawn with (fieldPointToPixmap) and the label overlay is
        read with (ZarrLayer._zarrIndex), so the three agree at every zoom
        and pan. Nothing is scaled or placed through Qt, which rounds.

            Params:
                pmw, pmh (int): the screen size in pixels
                tform (Transform): the section transform
                mag (float): the image magnification (microns per pixel)
                scale_level (int): image pixels per source pixel (zarr pyramids)
            Returns:
                (QImage) the pmw by pmh image layer, black where the image is not
        """
        wx, wy, ww, wh = tuple(self.series.window)
        k = scale_level
        unit = mag * k  # field units per source pixel
        a, b, c, d, e, f = tform._affine(True)  # field -> untransformed field
        sx = pmw * mag / ww  # screen pixels per image pixel
        sy = pmh * mag / wh

        if self.is_zarr_file:
            lh, lw = self.image.shape
        else:
            lh, lw = self._pixels.shape

        image_layer = _blank(pmw, pmh)
        px = np.arange(pmw)
        py = np.arange(pmh)

        if b == 0 and d == 0:
            # scale and translation only: one source column per screen column
            # and one source row per screen row, the same arithmetic as the
            # label overlay (the untransformed field of the window's left edge
            # and of its top edge, then on by screen pixel centers)
            cols = _zarrIndex(px, (a * wx + c) / unit, sx * k / a)
            rows = _zarrIndex(py, lh - (e * (wy + wh) + f) / unit, sy * k / e)
            in_x = np.flatnonzero((cols >= 0) & (cols < lw))
            in_y = np.flatnonzero((rows >= 0) & (rows < lh))
            if in_x.size == 0 or in_y.size == 0:
                return image_layer
            x0, x1 = int(in_x[0]), int(in_x[-1]) + 1
            y0, y1 = int(in_y[0]), int(in_y[-1]) + 1
            cols = cols[x0:x1]
            rows = rows[y0:y1]
            if self.is_zarr_file:
                c0, c1 = int(cols.min()), int(cols.max()) + 1
                r0, r1 = int(rows.min()), int(rows.max()) + 1
                src = self.image[r0:r1, c0:c1]
                cols = cols - c0
                rows = rows - r0
                screen = np.take(np.take(src, rows, axis=0), cols, axis=1)
            else:
                src = self._pixels.pixels
                # taking rows copies whole rows; taking columns gathers one
                # pixel at a time, so gather over the smaller of the visible
                # row span (zoomed in) and the screen's rows (zoomed out)
                r0, r1 = int(rows.min()), int(rows.max()) + 1
                if r1 - r0 <= rows.size:
                    screen = np.take(
                        np.take(src[r0:r1], cols, axis=1), rows - r0, axis=0
                    )
                else:
                    screen = np.take(np.take(src, rows, axis=0), cols, axis=1)
        else:
            # a rotation or shear: every screen pixel maps on its own
            fx = wx + (px + 0.5) * (mag / sx)
            fy = wy + (pmh - py - 0.5) * (mag / sy)
            ux = np.add.outer((b * fy + c) / unit, (a / unit) * fx)
            np.floor(ux, out=ux)
            uy = np.add.outer(lh - (e * fy + f) / unit, (-d / unit) * fx)
            np.floor(uy, out=uy)
            cols = ux.astype(np.int64)
            rows = uy.astype(np.int64)
            # unsigned compare: a negative index is out of range too
            inside = (cols.view(np.uint64) < lw) & (rows.view(np.uint64) < lh)
            if not inside.any():
                return image_layer
            if self.is_zarr_file:
                c0, c1 = int(cols[inside].min()), int(cols[inside].max()) + 1
                r0, r1 = int(rows[inside].min()), int(rows[inside].max()) + 1
                src = np.ascontiguousarray(self.image[r0:r1, c0:c1])
                cols -= c0
                rows -= r0
                flat_src, stride = src.ravel(), src.shape[1]
            else:
                flat_src, stride = self._pixels.flat, self._pixels.stride
            flat = rows * stride
            flat += cols
            # out of range indices read some pixel or other; masked below
            screen = np.take(flat_src, flat, mode="clip")
            x0, y0 = 0, 0

        if self.is_zarr_file:
            fmt, lut = QImage.Format.Format_Grayscale8, None
        else:
            fmt, lut = self._pixels.format, self._pixels.lut
        if lut is not None:
            screen = lut[screen]
        if b != 0 or d != 0:
            # after the color table, so an Indexed8 image's entry 0 is not
            # mistaken for black outside the image; opaque black for the
            # 32-bit formats, since Qt copies an RGB32 word's alpha as is
            screen[~inside] = 0xFF000000 if screen.dtype == np.uint32 else 0
        screen = np.ascontiguousarray(screen)
        im_screen = QImage(
            screen.data,
            screen.shape[1],
            screen.shape[0],
            screen.strides[0],
            fmt
        )
        painter = QPainter(image_layer)
        painter.drawImage(x0, y0, im_screen)
        painter.end()
        return image_layer

    def _cropWindow(self, tform : Transform, mag : float, scale_level : int) -> QImage:
        """The image pixels under the window's bounding box, uncropped by the screen.

        Only the brightness and contrast optimizer uses this; the drawn layer
        comes from _sampleWindow.
        """
        wx, wy, ww, wh = tuple(self.series.window)
        iw, ih = self.bw, self.bh
        poly_window = [
            (wx, wy),
            (wx, wy + wh),
            (wx + ww, wy + wh),
            (wx + ww, wy)
        ]
        utf_poly_window = tform.map(poly_window, inverted=True)
        utf_pixel_poly_window = [(x / mag, y / mag) for x, y in utf_poly_window]
        bounds = getBounds(utf_pixel_poly_window)
        bounds, filling = adjustBounds(bounds, iw, ih)
        if bounds is None:
            return _blank(*self.pixmap_dim)
        fxmin, fymin, fxmax, fymax = bounds        # floats: see adjustBounds
        # crop outward to whole pixels so the crop covers the window's span
        if self.is_zarr_file:
            zh_total, zw_total = self.image.shape
            zx0 = max(0, math.floor(fxmin / scale_level))
            zy0 = max(0, math.floor(fymin / scale_level))
            zx1 = min(zw_total, math.ceil(fxmax / scale_level))
            zy1 = min(zh_total, math.ceil(fymax / scale_level))
            zarr_saved = np.ascontiguousarray(
                self.image[zh_total - zy1: zh_total - zy0, zx0:zx1]
            )
            zh, zw = zarr_saved.shape
            im_crop = QImage(
                zarr_saved.data,
                zw,
                zh,
                zarr_saved.strides[0],
                QImage.Format.Format_Grayscale8
            )
            # copy so the returned image owns its data
            return im_crop.copy()
        cx0 = max(0, math.floor(fxmin))
        cy0 = max(0, math.floor(fymin))
        cx1 = min(iw, math.ceil(fxmax))
        cy1 = min(ih, math.ceil(fymax))
        return self.image.copy(QRect(cx0, ih - cy1, cx1 - cx0, cy1 - cy0))

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

def _blank(w : int, h : int) -> QImage:
    """A black image layer."""
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.black)
    return image


_BYTE_FORMATS = (QImage.Format.Format_Grayscale8, QImage.Format.Format_Indexed8)
_WORD_FORMATS = (
    QImage.Format.Format_RGB32,
    QImage.Format.Format_ARGB32,
    QImage.Format.Format_ARGB32_Premultiplied,
)


def _sampleableImage(image : QImage) -> QImage:
    """The image in a format with one byte or one 32-bit word per pixel.

    Those are read in place by _PixelView. Anything else (16-bit gray, 1-bit,
    24-bit RGB, 16-bit RGBA) is converted once, here, and never again per
    view. Gray without alpha becomes Grayscale8; everything else keeps its
    alpha as ARGB32.
    """
    if image.format() in _BYTE_FORMATS or image.format() in _WORD_FORMATS:
        return image
    if image.isGrayscale() and not image.hasAlphaChannel():
        return image.convertToFormat(QImage.Format.Format_Grayscale8)
    # not premultiplied: the brightness and contrast optimizer reads the
    # crop's values, and premultiplying would change them under alpha
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def _drawableImage(loaded : QImage, sampleable : QImage) -> QImage:
    """The image _sampleWindow draws from.

    A 16-bit image with alpha is premultiplied at 16 bits and then brought
    to 8, which rounds once, as drawing the 16-bit image itself would. Going
    through the 8-bit ARGB32 kept for the crop would round twice and land a
    level off on about a quarter of the pixels.
    """
    if sampleable is loaded or not loaded.hasAlphaChannel():
        return sampleable
    return loaded.convertToFormat(
        QImage.Format.Format_RGBA64_Premultiplied
    ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


class _PixelView:
    """Zero-copy numpy views of a QImage's pixels.

    `pixels` is (h, w), uint8 for one-byte formats and uint32 for 32-bit
    ones. `flat` is the whole padded buffer in one dimension with `stride`
    elements per row, for a single gather. `format` is what an array of
    those values draws as, and `lut` maps an Indexed8 value to its ARGB color.
    The QImage must outlive the view; ImageLayer keeps it on self.image.
    """

    def __init__(self, image : QImage):
        h, w, bpl = image.height(), image.width(), image.bytesPerLine()
        buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
        self.lut = None
        if image.format() in _WORD_FORMATS:
            self.flat = buf.view(np.uint32)
            self.stride = bpl // 4
            self.pixels = self.flat.reshape(h, self.stride)[:, :w]
            self.format = image.format()
        else:
            self.flat = buf
            self.stride = bpl
            self.pixels = buf.reshape(h, bpl)[:, :w]
            if image.format() == QImage.Format.Format_Indexed8:
                # all 256 entries, opaque black past the palette: a row's
                # padding bytes or a value beyond a short palette must not
                # index past the table
                table = image.colorTable()
                self.lut = np.full(256, 0xFF000000, dtype=np.uint32)
                self.lut[:len(table)] = np.array(table, dtype=np.uint32)
                self.format = QImage.Format.Format_ARGB32
            else:
                self.format = QImage.Format.Format_Grayscale8
        self.shape = (h, w)


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

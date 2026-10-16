from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtCore import Qt

from .image_layer import ImageLayer
from .trace_layer import TraceLayer

from PyReconstruct.modules.datatypes import (
    Series,
    Section
)


class SectionLayer(ImageLayer, TraceLayer):

    def __init__(self, section : Section, series : Series, load_image_layer=True):
        """Create the section layer object.
        
            Params:
                section (Section): the section object for the layer
                series (Series): the series object
        """
        if load_image_layer:
            ImageLayer.__init__(self, section, series)
            
        TraceLayer.__init__(self, section, series)
    
    def generateView(
        self,
        pixmap_dim : tuple,
        window : list,
        generate_image=True,
        generate_traces=True,
        hide_traces=False,
        show_all_traces=False,
        hide_image=False,
        focus_on=False,
        roi_box=None,
        ):
        """Generate pixmap view for a section.
        
            Params:
                pixmap_dim (tuple): the dimensions of the view
                window (list): the x, y, w, h of the field view
                generate_image (bool): whether or not to regenerate the image
                generate_traces (bool): whether or not to regenerate the traces
                focus_on (str): name of object to focus on
                roi_box (tuple): the ROI box (center x, center y, width,
                    height in field units), or None
        """
        ## Save attributes
        self.series.window = window
        self.pixmap_dim = pixmap_dim
        
        ## Set series screen mag and scaling
        self.series.screen_mag = window[2] / pixmap_dim[0]
        self.scaling = pixmap_dim[0] / (window[2] / self.section.mag)

        ## Generate image
        if hide_image:
            self.image_layer = QPixmap(*pixmap_dim)
            self.image_layer.fill(Qt.black)
        elif generate_image:
            self.image_layer = self.generateImageLayer(pixmap_dim, window)
        
        ## Kept even when the traces are hidden, so picking never sees a stale box
        self.roi_box = roi_box

        ## Hide all traces if requested. Nothing is drawn, so nothing is in
        ## view: a list left from an earlier draw would let a click pick a
        ## trace that is not on the screen (or not inside a moved ROI box)
        if hide_traces:
            self.traces_in_view = []
            return self.image_layer.copy()        

        if generate_traces:
            self.trace_layer = self.generateTraceLayer(
                pixmap_dim,
                window,
                show_all_traces,
                window_moved=generate_image,
                focus_on=focus_on,
                roi_box=roi_box
            )
        
        ## Combine pixmaps
        view = self.image_layer.copy()
        painter = QPainter(view)
        painter.drawPixmap(0, 0, self.trace_layer)
        painter.end()

        return view


r"""Export a series and one set of contours to a zarr store.

**This script does not run.** It is deliberately not repaired here, and it is
not shipped: ``[tool.setuptools.exclude-package-data]`` in ``pyproject.toml``
keeps ``assets/misc/*`` out of the wheel and the installers, so no installed
copy of PyReconstruct contains this file. It is documented rather than fixed or
deleted because no consumer of its output has been identified, and its output
format is not the one the maintained exporter writes -- see the table below.

Three independent failures, each reproduced by running this file against
``main`` at ``d001c4e4``. Loci are given by symbol rather than by line, because
line numbers drift and these two files drift independently:

1. **The path is a placeholder.** ``jser_fp`` below is literally
   ``r"C:\path\to\Series\DSNYJ_JSER\DSNYJ.jser"``. It sits under the
   ``# user-entered info`` comment, so it is arguably meant to be edited, but it
   means the file as committed cannot run anywhere. The ``Series.openJser(jser_fp)``
   call below raises::

       FileNotFoundError: [Errno 2] No such file or directory:
       'C:\\path\\to\\Series\\DSNYJ_JSER\\DSNYJ.jser'

2. **``generateLabelsArray`` has a different signature now.** The call below
   passes ``contour_names``, a list of ``str``. ``TraceLayer.generateLabelsArray``
   in ``PyReconstruct/modules/backend/view/trace_layer.py`` declares
   ``(self, pixmap_dim, window, traces: list[Trace], tform: Transform = None)``
   and its body reads ``trace.name`` off every element. That signature dates to
   ``a391ebc5`` (2023-05-05, "Modify autoseg UI structure"), so the drift is at
   least that old and the script has not run since. Fill the ``# user-entered info``
   block in with a real series and the ``labels_zarr[z] = ...`` statement below
   raises, inside ``generateLabelsArray``::

       AttributeError: 'str' object has no attribute 'name'

3. **Its return value is a 2-tuple, assigned straight into a zarr slot.**
   ``generateLabelsArray`` returns ``(arr, id_lookup_table)`` -- an ndarray and a
   dict -- and the ``labels_zarr[z] = ...`` statement below writes that return
   value directly into the zarr. Step over failure 2 by passing real ``Trace``
   objects and the same statement raises, this time from ``numpy`` under
   ``zarr.core.Array.__setitem__``::

       ValueError: setting an array element with a sequence. The requested array
       has an inhomogeneous shape after 1 dimensions. The detected shape was
       (2,) + inhomogeneous part.

Everything else still resolves: that last run reached failure 3 through
``Series.openJser``, ``Series.loadSection``, ``SectionLayer(section, series)``,
``SectionLayer.generateImageArray`` and ``zarr.Group.zeros`` without complaint.

**Where the maintained equivalent lives.**
``PyReconstruct/modules/backend/autoseg/conversions.py`` has ``seriesToZarr``
(raw) and ``seriesToLabels`` (labels), driven from the GUI, threaded, with a
progress bar and group or tag selection, and covered by the test suite.
``exportTraces`` in that file is the call pattern this script is missing: it
gathers real ``Trace`` objects out of ``section.contours``, then unpacks the
2-tuple into the array and a ``gt_lookup`` attribute.

**That is a pointer, not a drop-in replacement.** The attribute vocabulary
differs, so anything written to read a store this script produced will not read
one the in-app exporter produces:

    what this script writes    what ``conversions.py`` writes
    ------------------------   --------------------------------
    ``resolution``             ``voxel_size``
    ``srange`` (a 2-tuple)     ``sections`` (an explicit list)
    dataset ``labels``         dataset ``labels_<group_or_tag>``
    (nothing)                  ``axis_names``, ``units``
    labels dtype ``uint32``    labels dtype ``uint64``

``offset``, ``window``, ``true_mag`` and ``alignment`` keep the same names in
both, and ``get_resolution``/``get_thickness``/``get_true_mag`` in
``conversions.py`` do read ``resolution`` first and fall back to ``voxel_size``,
so a compatibility shim for the older name already exists on the read side.
``srange`` has no such shim: nothing in this repository reads a zarr ``srange``
attribute at all. The one in-tree reader that did, ``assets/misc/zarr_to_jser.py``,
was deleted for that reason -- ``labelsToObjects`` in ``conversions.py``, reached
from "Import labels", does its job.
"""

import os
import sys
import numpy as np
import zarr

from PySide6.QtWidgets import QApplication

# add src modules to the system path
sys.path.append(os.path.join(os.getcwd(), "..", ".."))
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.view import SectionLayer

# user-entered info
jser_fp = r"C:\path\to\Series\DSNYJ_JSER\DSNYJ.jser"
contour_names = ["d001"]  # use drop-down method with object groups
srange = (100, 151)  # enter manually
window = [16, 15, 10, 10]  # use a stamp (make one of the palette traces a freaking square)
mag = 0.005  # enter manually, but default to section mag

# calculate field attributes
shape = (
    srange[1] - srange[0],
    round(window[3]/mag),
    round(window[2]/mag)
)
pixmap_dim = shape[2], shape[1]  # the w and h of a 2D array

# create the zarr files
data_zg = zarr.open(os.path.join(
    os.path.dirname(jser_fp),
    "data.zarr"
))
raw_zarr = data_zg.zeros("raw", shape=shape, dtype=np.uint8)
labels_zarr = data_zg.zeros(f"labels", shape=shape, dtype=np.uint32)

# open the series
series = Series.openJser(jser_fp)

# open a QApp
app = QApplication([])

# iterate through series
alignment = {}
for snum in range(*srange):
    print(f"Working on section {snum}...")
    section = series.loadSection(snum)
    slayer = SectionLayer(section, series)
    z = snum - srange[0]
    raw_zarr[z] = slayer.generateImageArray(
        pixmap_dim, 
        window
    )
    labels_zarr[z] = slayer.generateLabelsArray(
        pixmap_dim,
        window,
        contour_names
    )
    alignment[str(snum)] = section.tforms[series.alignment].getList()

# get values for saving zarr files (from last known section)
z_res = int(section.thickness * 1000)
xy_res = int(mag * 1000)
resolution = [z_res, xy_res, xy_res]
offset = [0, 0, 0]

# save attributes
raw_zarr.attrs["offset"] = offset
raw_zarr.attrs["resolution"] = resolution

labels_zarr.attrs["offset"] = offset
labels_zarr.attrs["resolution"] = resolution

# save additional attributes for loading back into jser
raw_zarr.attrs["window"] = window
raw_zarr.attrs["srange"] = srange
raw_zarr.attrs["true_mag"] = mag
raw_zarr.attrs["alignment"] = alignment

labels_zarr.attrs["window"] = window
labels_zarr.attrs["srange"] = srange
labels_zarr.attrs["true_mag"] = mag
labels_zarr.attrs["alignment"] = alignment

# close the series
series.close()
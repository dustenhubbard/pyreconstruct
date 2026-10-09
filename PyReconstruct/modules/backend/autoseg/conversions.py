import os
import shutil
import threading
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Union, List, Tuple

import cv2
import zarr

from PyReconstruct.modules.datatypes import Series, Transform, Trace
from PyReconstruct.modules.backend.view import SectionLayer
from PyReconstruct.modules.backend.view.trace_layer import labelIds
from PyReconstruct.modules.backend.threading import ThreadPoolProgBar
from PyReconstruct.modules.calc import reducePoints

from .palette import AUTOSEG_TRACE_PREFIX, DEFAULT_AUTOSEG_PALETTE, palette_color

## Serializes every write importSection makes into SHARED series state. The
## import fans out over up to ten workers, and both mutations below are races
## without it: object_groups.add is check-then-act (two workers creating the
## same seg_ group each install a fresh set, one worker's objects vanish from
## the group), and section.save rewrites per-object aggregates in SeriesData
## that other workers' sections are rewriting at the same time (found
## 2026-08-28). The heavy work -- contour extraction, trace building -- stays
## outside the lock, so the parallelism the pool exists for is kept.
_SHARED_SERIES_LOCK = threading.Lock()


dt = None


def setDT():
    """Set date and time."""

    global dt
    now = datetime.now()
    dt = now.strftime("%Y%m%d_%H%M")


def get_zarr_array(zarr: zarr.hierarchy.Group, path: str="raw"):
    """Find and return array in zarr container."""

    from zarr import Array as z_array

    if isinstance(zarr[path], z_array):

        return zarr[path]
    
    elif isinstance(zarr[f"{path}/s0"], z_array):

        return zarr[f"{path}/s0"]

    else:

        raise ValueError("No zarr array found.")


def get_voxel_size_um(zarr_array):
    """Get the (z, y, x) voxel size of a zarr in µm.

    Reads ``resolution`` or ``voxel_size``. Neuroglancer stores these in nm, so
    they are divided by 1000 unless ``units`` says µm. Four entries are
    channel first, as in ``as_nm``. Raises KeyError if the zarr has neither
    attribute.
    """

    voxel_size = _spatial_axes(get_resolution(zarr_array))

    return [
        v if um else v / 1000
        for v, um in zip(voxel_size, _in_um(zarr_array, len(voxel_size)))
    ]


def _spatial_axes(entries):
    """The (z, y, x) entries of per-axis zarr metadata.

    Four entries are channel first, so the leading one is dropped. Any other
    length comes back as it is.
    """

    return list(entries[-3:]) if len(entries) == 4 else entries


def _in_um(zarr_array, n):
    """For each of n spatial axes, True if the zarr's ``units`` say µm (default nm).

    A four-entry ``units`` list is channel first like the values it describes,
    so its last three entries name the spatial axes.
    """

    units = zarr_array.attrs.get("units", "nm")
    if isinstance(units, str):
        units = [units] * n
    else:
        units = _spatial_axes(units)

    return [str(u).lower() in ("um", "µm", "μm", "micrometer", "micron") for u in units]


def as_nm(values, zarr_array):
    """Sizes or offsets given in a zarr's ``units``, in nm per (z, y, x) axis.

    Four values are channel first, so the channel entry is dropped before the
    rest are paired with ``units``, which may name three axes or four. Paired
    as given, four values against three units came back as channel, z and y.

    µm values round to a millionth of a nm, so a grid declared in µm reads
    the same as that grid in nm (0.0041 µm is 4.1 nm, not
    4.1000000000000005). nm values come back as they are.
    """

    values = _spatial_axes(values)

    return [
        round(v * 1000, 6) if um else v
        for v, um in zip(values, _in_um(zarr_array, len(values)))
    ]


def get_label_offset(labels_array, raw):
    """Where a labels array starts against raw, in nm per (z, y, x) axis.

    Both offsets are positions in the same space, so an offset the two
    arrays share moves neither. A four-entry offset is channel first, so
    only its spatial axes are compared. Labels with no ``offset`` start at
    raw's corner, as they always have.
    """

    if "offset" not in labels_array.attrs:
        return [0, 0, 0]

    offset = as_nm(get_array_offset(labels_array), labels_array)
    raw_offset = as_nm(get_array_offset(raw), raw)

    return [o - r for o, r in zip(offset, raw_offset)]


def get_true_mag(zarr_array):
    """Get true magnification (µm per pixel) of a zarr.

    Prefers ``true_mag`` (written by PyReconstruct in µm), then the x voxel
    size converted to µm.
    """

    if "true_mag" in zarr_array.attrs:
        return zarr_array.attrs["true_mag"]

    try:
        return get_voxel_size_um(zarr_array)[-1]
    except KeyError:  # no resolution provided
        return 0.004  # default to x, y res of 4 nm × 4 nm


def get_array_offset(zarr_array):
    """Get offset of a zarr array."""

    try:
        offset = zarr_array.attrs["offset"]

    except KeyError:
        offset = [0, 0, 0]

    return offset


def get_resolution(zarr_array):
    """Get resolution of a zarr array."""

    try:
        resolution = zarr_array.attrs["resolution"]

    except KeyError:
        resolution = zarr_array.attrs["voxel_size"]

    return resolution


def get_thickness(zarr_array):
    """Get section thickness (in µm) of series in zarr format."""

    try:
        return get_voxel_size_um(zarr_array)[0]
    except KeyError:  # no resolution provided
        return 0.05  # the default section thickness, as get_true_mag defaults


def get_label_resolutions(labels_array, raw, series=None, raw_attrs=None):
    """Get the (labels, raw) resolutions for a label import.

    Both come back in nm, whatever ``units`` each array declares. Missing or
    zero raw axes use the exporter's grid: the first exported section's
    thickness and the saved export mag (or raw's metadata/default mag). Missing or
    zero label axes share raw's grid. Four-entry metadata on either array is
    channel first; ``as_nm`` keeps only its last three spatial axes. The
    existing metadata/default fallback applies when the series section is
    unavailable.
    """

    try:
        raw_res = as_nm(get_resolution(raw), raw)
    except KeyError:
        raw_res = [0, 0, 0]

    if 0 in raw_res:
        attrs = raw.attrs if raw_attrs is None else raw_attrs
        thickness = get_thickness(raw)
        if series is not None and raw_res[0] == 0:
            sections = attrs.get("sections", [])
            if sections and sections[0] in series.sections:
                thickness = series.data["sections"][sections[0]]["thickness"]
        mag = attrs.get("true_mag") or get_true_mag(raw)
        fallback = [voxel_nm(thickness), voxel_nm(mag), voxel_nm(mag)]
        raw_res = [r if r != 0 else f for r, f in zip(raw_res, fallback)]
        if any(r <= 0 for r in raw_res):
            raise ValueError("Cannot recover a nonzero series resolution for this Zarr.")

    try:
        labels_res = as_nm(get_resolution(labels_array), labels_array)
    except KeyError:
        labels_res = [0, 0, 0]

    if 0 in labels_res:  # only fill zero axes; keep any axes raw lacks
        labels_res = [
            r if r != 0 or i >= len(raw_res) else raw_res[i]
            for i, r in enumerate(labels_res)
        ]
    return labels_res, raw_res


def voxel_nm(size_um):
    """A size in µm as nm for ``voxel_size``.

    Whole numbers stay ints, as they always were. Anything else keeps its
    fraction: int() made 2.54 nm pixels 2 nm and 0.5 nm pixels 0.
    """

    return _exact_nm(size_um * 1000)


def _exact_nm(nm):
    """A length in nm, rounded to a millionth of a nm; whole numbers as ints."""

    nm = round(nm, 6)
    return int(nm) if float(nm).is_integer() else nm


def get_offset(window, resolution, img_mag, relative_to, section_diff=0):
    """Calculate offset from a window."""

    lat, ax = window

    ul_all = (
        relative_to[0],
        relative_to[1] + relative_to[3]
    )

    ul_roi_group= (
        lat[0],
        lat[1] + lat[3]
    )

    ## Do the things...

    scale_x = resolution[2] / 1000 / img_mag
    scale_y = resolution[1] / 1000 / img_mag

    x_diff_real = ul_roi_group[0] - ul_all[0]
    y_diff_real = ul_roi_group[1] - ul_all[1]

    x_diff_scaled = x_diff_real * scale_x
    y_diff_scaled = y_diff_real * scale_y

    ## the fraction stays: whole nm lost up to a pixel at 0.5 nm pixels
    x = _exact_nm(x_diff_scaled * 1000)
    y = _exact_nm(y_diff_scaled * 1000)
    
    z = section_diff * resolution[0]  # offset in z

    offset = [z, -y, x]

    return offset


def rechunk(
        zarr_fp: Union[str, Path],
        target_chunks: Tuple[int, int, int] = (8, 256, 256)
):
    """Rechunk all available datasets."""

    import dask.array as da

    if not isinstance(zarr_fp, Path):
        zarr_fp = Path(zarr_fp)
    
    z = zarr.open(str(zarr_fp), "r")

    for arr_name, src_arr in z.items():

        if not isinstance(src_arr, zarr.Array):
            continue

        src_fp = zarr_fp / arr_name
        target_fp = src_fp.with_name(arr_name + "_rechunked")
        
        da_old = da.from_zarr(src_fp)
        da_new = da_old.rechunk((8, 256, 256))
        
        da_new.to_zarr(target_fp)

        zarr.open(target_fp, "r+").attrs.update(src_arr.attrs)

        ## Remove original
        shutil.rmtree(str(src_fp))
        target_fp.rename(src_fp)
        
    return True


def groupsToVolume(series: Series, groups: list=None, padding: float=None, restrict_to_sections: list=None):
    """Convert objects in groups into a volume based on max and min x/y/section values.

        Params:
            group_name (str): group to include in zarr
            series (Series): a series object
            srange (tuple): the range of sections (exclusive)
            padding (float): padding (μm) to add around object
            restrict_to_sections (list): restrict volume to sections
        Returns:
           [x position, y position, width, height], [start, end]
    """
    
    group_objects = []
    x_vals = []
    y_vals = []
    sec_range = set()
    
    if groups:
        for group in groups:
            group_objects += series.object_groups.getGroupObjects(group)

    for snum, section in series.enumerateSections():

        tform = section.tform

        # for each object to be included...

        for border_obj in group_objects:
        
            if border_obj in section.contours:

                xmin, ymin, xmax, ymax = section.contours[border_obj].getBounds(tform)

                sec_range.add(snum)
                x_vals += [xmin, xmax]
                y_vals += [ymin, ymax]

    ## Named errors instead of bare min()-of-empty ValueErrors: a typo'd
    ## group name (or a filter that excludes everything) used to die with
    ## "min() arg is an empty sequence" and no hint of which input was
    ## empty (found 2026-08-28).
    if not x_vals:
        names = ", ".join(groups) if groups else "(no groups given)"
        raise ValueError(
            f"no traces found for the requested group(s): {names}. Check the "
            "group names and that their objects have traces."
        )

    x = min(x_vals)
    w = max(x_vals) - x
    y = min(y_vals)
    h = max(y_vals) - y

    if restrict_to_sections:
        start, end = restrict_to_sections
        sec_range = [sec for sec in sec_range if sec >= start and sec <= end]
        if not sec_range:
            raise ValueError(
                f"the requested group(s) have no traces between sections "
                f"{start} and {end}."
            )
        sec_range = [min(sec_range), max(sec_range) + 1]
    else:
        ## the documented contract: [start, end], not a raw set
        sec_range = [min(sec_range), max(sec_range) + 1]

    if padding:
        
        x -= padding
        y -= padding
        w += (padding * 2)
        h += (padding * 2)

    window = [x, y, w, h]

    return window, sec_range


def createZarrName(window):
    """Return string representing a zarr file name"""

    window_str = [str(round(elem, 2)) for elem in window]
    return f'data_{"-".join(window_str)}.zarr'


def seriesToZarr(series : Series,
                 sections : list,
                 mag : float,
                 window : list,
                 data_fp: str = None,
                 output_dir: str = None,
                 other_attrs: dict = None,
                 chunk_size: tuple = (1, 256, 256)):
    """Convert a series of images into a neuroglancer-compatible zarr.
    
        Params:
            series (Series): the series to convert
            sections (list): the sections to include (exclusive; ASSUME sorted already)
            mag (float): the microns per pixel for the zarr file
            window (list): the window (x, y, width, height) for the resulting zarr
            data_fp (str): filename of output zarr
            output_dir (str): directory to store zarr
            other_attrs (dict): other infoformation to store in .zattrs

        Returns:
            the filepath for the zarr (None if a section failed)
    """

    ## Calculate field attributes
    shape = (
        len(sections),          # z
        round(window[3]/mag),   # h
        round(window[2]/mag)    # w
    )

    pixmap_dim = shape[2], shape[1]  # w and h of a 2D array

    ## Create zarr
    
    if not data_fp:  # if no data_fp provided, place with jser
        
        zarr_name = createZarrName(window)
        
        if not output_dir:
            output_dir = os.path.dirname(series.jser_fp)
            
        data_fp = os.path.join(output_dir, zarr_name)
        
    ## Delete only something that IS a zarr. data_fp is caller-supplied (the
    ## CLI wires --output straight through), and an unconditional rmtree
    ## recursively deleted whatever existing directory the user pointed at,
    ## no confirmation asked (found 2026-08-28).
    if os.path.isdir(data_fp):
        looks_like_zarr = data_fp.rstrip("/").endswith(".zarr") or any(
            os.path.exists(os.path.join(data_fp, marker))
            for marker in (".zgroup", ".zattrs", "zarr.json")
        )
        if not looks_like_zarr:
            raise ValueError(
                f"refusing to overwrite {data_fp}: it exists and does not "
                "look like a zarr (no .zgroup/.zattrs and no .zarr suffix). "
                "Choose an output path that does not exist or points at a "
                "zarr to replace."
            )
        shutil.rmtree(data_fp)  # delete existing zarr
        
    data_zg = zarr.open(data_fp, "a")
    
    data_zg.create_dataset(
        "raw",
        shape=shape,
        chunks=chunk_size,
        dtype=np.uint8
    )

    raw = data_zg["raw"]

    ## Get values for saving zarr files (from last known section)
    section_thickness = series.loadSection(sections[0]).thickness
    z_res = voxel_nm(section_thickness)
    xy_res = voxel_nm(mag)
    resolution = [z_res, xy_res, xy_res]
    offset = [0, 0, 0]

    ## Get series alignment
    alignment = {}
    for snum in sections:
        snum_tform = series.data["sections"][snum]["tforms"][series.alignment].getList()
        alignment[str(snum)] = snum_tform

    ## Save attributes
    raw.attrs["offset"] = offset
    raw.attrs["voxel_size"] = resolution 
    raw.attrs["axis_names"] = ["z", "y", "x"]
    raw.attrs["units"] = ["nm", "nm", "nm"]

    ## Save additional attributes for loading back into jser
    raw.attrs["window"] = window
    raw.attrs["sections"] = sections
    raw.attrs["true_mag"] = mag
    raw.attrs["alignment"] = alignment

    ## Save other info to root .zattrs
    if other_attrs:
        for k, v in other_attrs.items():
            data_zg.attrs[k] = v
    
    ## Create threadpool and interate through series
    threadpool = ThreadPoolProgBar()
    
    for i, snum in enumerate(sections):
        threadpool.createWorker(
            exportSection,
            data_zg,
            snum,
            series,
            i,
            window,
            pixmap_dim
        )
        
    if not threadpool.startAll("Converting series to zarr..."):
        shutil.rmtree(data_fp)  # a failed worker left blank sections
        return None

    return data_fp
    

def seriesToLabels(series: Series,
                   data_fp: str,
                   group: Union[str, None] = None,
                   window: Union[List, None] = None,
                   img_mag: float = 0.00254,
                   chunk_size: tuple = (1, 256, 256),
                   raw_window: Union[List, None] = None):
    """Export contours as labels to an existing zarr.
    
        Params:
            series (Series): the series
            data_fp (str): the filepath for the zarr
            group (str): the group to export as labels (None if retraining)
        Returns:
            (bool) True if every section exported
    """

    # extract data from raw
    data_zg = zarr.open(data_fp)
    raw = data_zg["raw"]

    shape = raw.shape
    mag = get_true_mag(raw)
    ## the labels are written in nm, whatever units raw declares
    resolution = as_nm(get_resolution(raw), raw)
    raw_offset = as_nm(get_array_offset(raw), raw)
    alignment = raw.attrs["alignment"]

    if window:

        ## window is (x, y, w, h), (start, end): the section range is its
        ## second element, so it can only be read inside this branch. Only
        ## sections in the zarr count: a deleted section leaves a gap in the
        ## numbers but no slice in raw, so the labels start at the z where
        ## their first section sits in raw, not at a section number offset.
        start, end = window[1]
        raw_sections = list(raw.attrs["sections"])
        sections = [snum for snum in raw_sections if start <= snum < end]
        if not sections:
            raise ValueError(
                f"the zarr has no sections between {start} and {end - 1}."
            )

        offset = get_offset(
            window,
            resolution,
            img_mag,
            relative_to=raw_window,
            section_diff=raw_sections.index(sections[0])
        )
        offset = [o + r for o, r in zip(offset, raw_offset)]

        window = window[0]

    else:

        ## seriesToZarr wrote both of these next to each other, so the sections
        ## come back from the same place the window does
        sections = list(raw.attrs["sections"])
        window = raw.attrs["window"]
        offset = raw_offset

    # calculate field attributes
    shape = (
        len(sections),
        round(window[3] / mag),
        round(window[2] / mag)
    )
    pixmap_dim = shape[2], shape[1]  # the w and h of the 2D array

    if group:
        
        is_group = True
        del_group = None
        group_or_tag = group
        
    # if retrain, use tag and search for group to delete
    else:
        
        is_group = False
        del_group = series.getRecentSegGroup()
        group_or_tag = f"{del_group}_keep"

    dataset_name = f"labels_{group_or_tag}"

    # create labels datasets
    data_zg.create_dataset(
        dataset_name,
        shape=shape,
        chunks=chunk_size,
        dtype=np.uint64
    )
    
    data_zg[dataset_name].attrs["offset"] = offset
    data_zg[dataset_name].attrs["voxel_size"] = resolution
    data_zg[dataset_name].attrs["axis_names"] = ["z", "y", "x"]
    data_zg[dataset_name].attrs["units"] = ["nm", "nm", "nm"]

    ## One label per object for the whole export, so an object keeps its label
    ## on every section and no two objects share one. Every worker draws only
    ## objects from this group.
    name_ids = labelIds(
        series.object_groups.getGroupObjects(group if is_group else del_group)
    )
    gt_lookup = {}

    # create threadpool
    threadpool = ThreadPoolProgBar()

    for i, snum in enumerate(sections):
        threadpool.createWorker(
            exportTraces,
            data_zg,
            snum,
            series,
            group_or_tag,
            is_group,
            i,
            window,
            pixmap_dim,
            del_group,
            alignment[str(snum)],
            name_ids,
            gt_lookup
        )

    if not threadpool.startAll("Converting contours to zarr..."):
        del data_zg[dataset_name]  # drop the partial labels
        return False

    ## written once here: a write from each worker kept only the last one's
    data_zg[dataset_name].attrs["gt_lookup"] = gt_lookup

    if del_group:
        series.object_groups.removeGroup(del_group)

    return True


def getLabelsToObjectsData(data_fp: str, group: str, raw_attrs: dict = None, series=None) -> tuple:

    data_zg = zarr.open(data_fp, "r")
    
    if group not in data_zg:
        return

    raw = get_zarr_array(data_zg, "raw")
    labels_array = get_zarr_array(data_zg, group)
    label_volume(labels_array)  # refuses several channels before any section starts
    sections = (raw.attrs if raw_attrs is None else raw_attrs)["sections"]

    resolution_z = get_label_resolutions(labels_array, raw, series, raw_attrs)[0][0]
    offset_z = get_label_offset(labels_array, raw)[0]
    section_start = round(offset_z / resolution_z)

    return data_zg, sections, section_start


def labelsToObjects(series : Series, data_fp : str, group : str, ids: list = None, raw_attrs: dict = None) -> None:
    """Convert labels in a zarr file to objects in a series.
    
        Params:
            series (Series): the series to import zarr data into
            data_zg (str): the filepath for the zarr group
            group (str): the name of the group with labels of interest
            ids (list): the labels to import (will import all if None)
            raw_attrs (dict): window, sections, true_mag and alignment to use
                instead of the ones stored on the zarr's raw array
        Returns:
            (bool) True if every section imported (None if group is missing)
    """

    data = getLabelsToObjectsData(data_fp, group, raw_attrs=raw_attrs, series=series)
    if data is None:  # group not present in the zarr
        return
    data_zg, sections, section_start = data

    ## Create threadpool and iterate across sections
    setDT()
    threadpool = ThreadPoolProgBar()

    ## The real section numbers, NOT range(section_start, ...):
    ## section_start is a Z-SLICE offset into the labels array, while
    ## `sections` holds actual section numbers, and the standard export
    ## skips the cal grid so the two disagree on almost every zarr. The old
    ## range made every default import fail its first worker (ValueError on
    ## a section below the export window) and, with a windowed export,
    ## silently imported the WRONG slice via negative-index wraparound
    ## (found 2026-08-28). importSection itself guards the bounds now.
    for snum in sections:
        threadpool.createWorker(
            importSection,
            data_zg,
            group,
            snum,
            series,
            ids,
            raw_attrs
        )

    return threadpool.startAll(f"Converting {group} to contours...")


def getExteriors(mask : np.ndarray) -> list[np.ndarray]:
    """Get exteriors from a mask.
    
        Params:
            mask (np.ndarray): the mask to extract exteriors from
        Returns:
            (list[np.ndarray]): the list of exteriors
    """
    cv_detected, hierarchy = cv2.findContours(
        mask.astype(np.uint8),
        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    
    exteriors = []

    for e in cv_detected:
        e = e[:,0,:]
        # invert the y axis
        # e[:,1] *= -1
        # e[:,1] += mask.shape[0]
        # reduce the points
        e = reducePoints(e, array=True)
        exteriors.append(e)

    return exteriors


def exterior_to_points(ext: list[np.ndarray], offset, resolution, raw, window, tform, mag, raw_resolution=None):
    """Convert exterior to trace points.

    ``ext`` is in label pixels. ``raw_resolution`` (default: the same as
    ``resolution``) gives the height of raw in label pixels for the y flip.
    ``offset`` is already relative to raw, from ``get_label_offset``; raw's
    own offset must not be applied a second time here.
    """

    if raw_resolution is None:
        raw_resolution = resolution

    ## Convert to float
    ext = ext.astype(np.float64)

    ## Add offset to coordinates
    ext[:,0] += offset[2] / resolution[2]  # x

    ext[:,1] += offset[1] / resolution[1]  # y
    ext[:,1] *= -1
    ## y is second to last in (z, y, x) and in channel first (1, z, y, x)
    ext[:,1] += raw.shape[-2] * (raw_resolution[1] / resolution[1])

    ## Convert to coordinates
    ext *= mag
            
    ## Add origin back (if ROI originaly exported with offset)
    ext[:,0] += window[0]
    ext[:,1] += window[1]
            
    ## Apply reverse transform
    trace_points = tform.map(ext.tolist(), inverted=True)

    return trace_points


def exportSection(data_zg,
                  snum : int,
                  series : Series,
                  z : int,
                  window : list,
                  pixmap_dim : tuple):
    """Export the raw data for a single section.
    
        Params:
            data_zg: the zarr group
            snum (int): the section number
            series (Series): the series
            z (int): the z-level of the section in the zarr
            window (list): the frame for the raw export
            pixmap_dim (tuple): the w and h in pixels for the arr output
    """
    # print(f"Section {snum} exporting started")
    section = series.loadSection(snum)
    slayer = SectionLayer(section, series)

    arr = slayer.generateImageArray(
        pixmap_dim, 
        window,
        bc=False
    )

    data_zg["raw"][z] = arr


def exportTraces(data_zg,
                 snum : int,
                 series : Series,
                 group_or_tag : str,
                 is_group : bool,
                 z : int,
                 window : list,
                 pixmap_dim : tuple,
                 del_group : str = None,
                 tform_list=None,
                 name_ids : dict = None,
                 gt_lookup : dict = None):
    """Export the traces as labels for a single section.
    
        Params:
            data_zg: the zarr group
            snum (int): the section number
            series (Series): the series
            group_or_tag (str): the group or tag to include as labels
            is_group (bool): True if the previous entry is a group, False if tag
            z (int): the z position of the section in the zarr
            window (list): the frame for the raw export
            pixmap_dim (tuple): the w and h in pixels for the arr output
            del_group (str): the group to delete
            tform_list (list): the transform to apply to the traces
            name_ids (dict): the label for each object name in the export
            gt_lookup (dict): filled with the name and label of each object drawn
    """
    section = series.loadSection(snum)
    slayer = SectionLayer(section, series, load_image_layer=False)
    if tform_list:
        tform = Transform(tform_list)
    else:
        tform = None

    ## Gather traces
    traces = []
    
    if is_group:
        group = group_or_tag
        for cname in series.object_groups.getGroupObjects(group):
            if cname in section.contours:
                traces += section.contours[cname].getTraces()

    else:
        tag = group_or_tag
        for cname in series.object_groups.getGroupObjects(del_group): # only search recent seg group to save time
            if cname in section.contours:
                for trace in section.contours[cname]:
                    if tag in trace.tags:
                        traces.append(trace)

    array, sec_id_dict = slayer.generateLabelsArray(
            pixmap_dim,
            window,
            traces,
            tform=tform,
            name_ids=name_ids
    )

    labels_name = f"labels_{group_or_tag}"

    data_zg[labels_name][z] = array
    if gt_lookup is not None:
        gt_lookup.update(sec_id_dict)

    # delete group if requested
    if not is_group:
        if del_group:
            deleted = False
            for cname in series.object_groups.getGroupObjects(del_group):
                if cname in section.contours:
                    del(section.contours[cname])
                    deleted = True
            if deleted:
                # Contours dropped from outside `Section`, so the columnar store
                # still holds their rows and its row map still keys on their
                # traces. Rebuild before the addTrace loop below, whose own
                # consistency check would otherwise raise on drift this deletion
                # caused rather than on anything the loop did.
                section.resyncColumnarStore()
            # add the traces of interest back in
            for trace in traces:
                trace.setHidden(True)
                section.addTrace(trace)
            # under the shared lock for the same reason importSection's save
            # is: this runs on the export pool's workers too
            with _SHARED_SERIES_LOCK:
                section.save()


class _FirstChannel:
    """Channel 0 of a (1, z, y, x) array, read and written as (z, y, x).

    Every index goes straight to the array, so nothing is read until a slice
    is asked for.
    """

    def __init__(self, array):
        self.array = array
        self.shape = tuple(array.shape[1:])

    def __len__(self):
        return self.shape[0]

    def __getitem__(self, key):
        return self.array[_channelKey(key)]

    def __setitem__(self, key, value):
        self.array[_channelKey(key)] = value


def _channelKey(key):
    return (0, *key) if isinstance(key, tuple) else (0, key)


def label_volume(labels_array):
    """A labels array as (z, y, x), the way import and the overlay index it.

    A 4D array is channel first, as its four-entry ``voxel_size`` is read.
    One integer channel is the labels, as ``is_label_array`` counts it. With
    more channels nothing says which one is, and a float channel is a
    prediction rather than label ids, so either is refused.
    """

    shape = getattr(labels_array, "shape", None)
    if shape is None or len(shape) != 4:
        return labels_array
    if shape[0] != 1:
        raise ValueError(
            f"This Zarr label array has {shape[0]} channels. PyReconstruct imports "
            "labels from a single channel, so save them as (z, y, x) or (1, z, y, x)."
        )
    if not np.issubdtype(labels_array.dtype, np.integer):
        raise ValueError(
            f"This Zarr label array is {labels_array.dtype}, not an integer type. "
            "PyReconstruct imports label ids, so save a prediction as integer "
            "labels before importing it."
        )
    return _FirstChannel(labels_array)


def raw_volume(raw):
    """A raw image array as (z, y, x), one grayscale image per section.

    A 4D array is channel first, as its four-entry ``voxel_size`` is read,
    and one channel is the images. Each section is stored and drawn as a
    single grayscale image, so several channels are refused rather than
    read as sections.
    """

    shape = raw.shape
    if len(shape) == 3:
        return raw
    if len(shape) == 4 and shape[0] == 1:
        return _FirstChannel(raw)
    if len(shape) == 4:
        raise ValueError(
            f"This Zarr raw array has {shape[0]} channels. PyReconstruct shows "
            "each section as one grayscale image, so save raw as (z, y, x) or "
            "(1, z, y, x)."
        )
    raise ValueError(
        f"This Zarr raw array has {len(shape)} axes. PyReconstruct reads raw "
        "as (z, y, x) or (1, z, y, x)."
    )


def is_label_array(array):
    """True if an overlay array holds label ids rather than an image.

    (z, y, x) arrays are labels, as they always were. A 4D array is channel
    first, and it is labels only as one integer channel. RGB images and
    affinities have three channels, and a float channel is a prediction.
    """

    shape = array.shape
    if len(shape) == 3:
        return True
    return (
        len(shape) == 4 and shape[0] == 1
        and np.issubdtype(array.dtype, np.integer)
    )


def importSection(data_zg, group, snum, series, ids=None, raw_attrs=None):
    """Import label data for a single section.
    
        Params:
            data_zg: the zarr group
            group: the name of the zarr group with data to import
            snum (int): the section number
            series (Series): the series
            ids (list): the ids to include in importing
            raw_attrs (dict): window, sections, true_mag and alignment to use
                instead of the ones stored on the zarr's raw array
    """
    
    labels_array = get_zarr_array(data_zg, group)
    raw = get_zarr_array(data_zg, "raw")
    resolution, raw_resolution = get_label_resolutions(labels_array, raw, series, raw_attrs)

    offset = get_label_offset(labels_array, raw)
    z_offset = round(offset[0] / resolution[0])

    ## by section: the first axis of a (1, z, y, x) array is its channel,
    ## and read as the section it sent a whole volume to findContours
    labels = label_volume(labels_array)

    attrs = raw.attrs if raw_attrs is None else raw_attrs
    window = attrs["window"]
    sections = attrs["sections"]
    mag = attrs["true_mag"] / raw_resolution[-1] * resolution[-1]

    ## Get section transformation
    try:
        alignment = attrs["alignment"]
        tform = Transform(alignment[str(snum)])
    except KeyError:
        return

    if snum not in series.sections:  # section not in the current series
        return
    if snum not in sections:  # section not in the zarr's export window
        return

    ## Load section and corresponding data
    z = sections.index(snum)

    ## Explicit bounds, both ends: a z below the labels dataset's offset used
    ## to reach zarr as a NEGATIVE index, which wraps to the far end of the
    ## array and silently imported another section's labels (found
    ## 2026-08-28). Only the high end ever raised.
    zi = z - z_offset
    if zi < 0:
        return
    # the high bound stays best-effort: array-likes without a shape fall
    # through to the BoundsCheckError catch below, as they always did
    shape = getattr(labels, "shape", None)
    if shape is not None and zi >= shape[0]:
        return

    section = series.loadSection(snum)

    try:
        arr = labels[zi]
    except zarr.errors.BoundsCheckError:  # return if out of bounds
        return

    pixmap_dim = (arr.shape[1], arr.shape[0])

    ## Modify window to adjust for offset and resolution
    zarr_window = window.copy()

    field_width = pixmap_dim[0] * mag
    field_height = pixmap_dim[1] * mag

    field_offset_x = offset[2] / resolution[2] * mag
    field_offset_y = offset[1] / resolution[1] * mag
    field_offset_y = field_height - field_offset_y  # account for zarr origin at top of image

    zarr_window[0] += field_offset_x
    zarr_window[1] += field_offset_y
    zarr_window[2] = field_width
    zarr_window[3] = field_height

    # # exclude areas that already have good traces (TEMPORARILY REMOVED)

    # # get groups/tags that are good
    # gts = []
    # for zg in data_zg:
    #     if zg.startswith("labels_"):
    #         gts.append(zg[len("labels_"):])
        
    # # gather traces with these groups or tags
    # traces = []
    # for trace in section.tracesAsList():
    #     for tag in trace.tags:
    #         if tag in gts:
    #             traces.append(trace)
    #             continue
    #     for g in gts:
    #         if trace.name in series.object_groups.getGroupObjects(g):
    #             traces.append(trace)

    # slayer = SectionLayer(section, series, load_image_layer=False)
    # exclude_arr = slayer.generateLabelsArray(
    #     pixmap_dim,
    #     zarr_window,
    #     traces,
    #     tform
    # )
    # arr[exclude_arr != 0] = 0

    ## Iterate through label ids
    if ids is None:
        ids = np.unique(arr)

    ## Resolve the trace-color palette + seed once for this section.
    ## An empty/unset override falls back to the shipped curated default.
    palette = series.getOption("autoseg_color_palette") or DEFAULT_AUTOSEG_PALETTE
    color_seed = series.getOption("autoseg_color_seed") or 0

    for id in ids:
        
        if id == 0:
            continue

        ## Get exteriors for ID
        exteriors = getExteriors(arr == id)

        ## Add exteriors as traces
        for ext in exteriors:

            trace_name = f"{AUTOSEG_TRACE_PREFIX}{id}"
            trace_color = palette_color(id, palette, color_seed)

            trace = Trace(name=trace_name, color=trace_color)
            trace.points = exterior_to_points(
                ext, offset, resolution, raw, window, tform, mag, raw_resolution
            )
            trace.fill_mode = ("transparent", "unselected")
            
            section.addTrace(trace)

        ## Add trace to group (under the shared lock: add is check-then-act)
        with _SHARED_SERIES_LOCK:
            series.object_groups.add(f"seg_{dt}", f"{AUTOSEG_TRACE_PREFIX}{id}")
            series.object_groups.add(f"seg_{group}", f"{AUTOSEG_TRACE_PREFIX}{id}")

    ## save rewrites shared per-object aggregates, so it takes the lock too
    with _SHARED_SERIES_LOCK:
        section.save()


def zarrToNewSeries(zarr_fp : str, label_groups : list, name : str):
    """Create a new series from a neuroglancer zarr.
    
        Params:
            zarr_fp (str): the filepath to the full neuroglancer zarr file
            label_groups (str): the list of label groups to include as contours
            name (str): the name of the new series
    """
    ## Read only: the source zarr is the user's data, and nothing below may
    ## change it. The window, sections and alignment the label import needs
    ## are worked out here and passed to it, not stored on the source.
    ng_zarr = zarr.open(zarr_fp, "r")
    raw = get_zarr_array(ng_zarr, "raw")  # assume "raw" exists as zarr path
    ## by section, before anything is written: a (1, z, y, x) raw is its one
    ## channel, and several channels are refused
    volume = raw_volume(raw)

    ## Get true mag
    true_mag = get_true_mag(raw)

    ## Set window
    z, y, x = volume.shape
    window = [0, 0, x * true_mag, y * true_mag]

    ## Set the sections
    sections = list(range(z))
    n_digits = len(str(sections[-1]))

    ## Set alignment
    alignment = {}
    
    for snum in sections:
        alignment[str(snum)] = Transform.identity().getList()

    raw_attrs = {
        "true_mag": true_mag,
        "window": window,
        "sections": sections,
        "alignment": alignment,
    }

    ## Get thickness
    thickness = get_thickness(raw)

    ## Create zarr containing the images
    ## (i.e., each section becomes an zarr group)

    images_dir = Path(zarr_fp).with_name(f"{name}_images.zarr")

    ## mkdir refuses a folder that is already there, Zarr or not, so the
    ## cleanup below only ever removes a folder this call made
    images_dir.mkdir(exist_ok=False)
    series = None

    try:
        images_zarr = zarr.open(images_dir, "w-")
        images_zarr.create_group("scale_1")
        images = images_zarr["scale_1"]
        image_locations = []

        for i, snum in enumerate(sections):

            src = f"section{snum:0{n_digits}d}"
            print(f"Working on {src}...")

            images.create_dataset(src, data=volume[i])

            img_loc = os.path.join(images_dir, "scale_1", src)
            image_locations.append(img_loc)

        ## Create new series
        series = Series.new(
            image_locations,
            name,
            true_mag,
            thickness
        )

        ## Import label data into series
        imported = True
        for label_group in label_groups:
            if label_group in ng_zarr:
                imported = labelsToObjects(
                    series,
                    zarr_fp,
                    label_group,
                    raw_attrs=raw_attrs,
                )
                if not imported:
                    break

    except BaseException:
        ## a partial images zarr would make a retry with this name fail;
        ## a close error must not hide the original one
        try:
            if series is not None:
                series.close()
        except Exception:
            pass
        finally:
            shutil.rmtree(images_dir, ignore_errors=True)
        raise

    if not imported:  # a section failed: drop the half-built series
        try:
            series.close()
        finally:
            shutil.rmtree(images_dir, ignore_errors=True)
        return None

    ## Return series
    return series

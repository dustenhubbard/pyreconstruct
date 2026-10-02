#!/usr/bin/env python

"""Create neuroglancer-formatted zarrs from PyReconstruct jser files."""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

import zarr

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.imports import modules_available

from PyReconstruct.modules.backend.func import stdout_to_devnull

from PyReconstruct.modules.datatypes import Series

from PyReconstruct.modules.backend.autoseg import (
    seriesToZarr,
    seriesToLabels,
    groupsToVolume,
    createZarrName,
    rechunk
)

from PyReconstruct.modules.backend.autoseg.conversions import get_true_mag

from PyReconstruct.assets.scripts.create_ng_zarr.parser import (
    get_args,
    parse_args
)

from PyReconstruct.assets.scripts.create_ng_zarr.utils import (
    print_flush,
    flatten_list,
    get_sha1sum,
    print_summary
)


qt_offscreen = os.getenv("QT_QPA_PLATFORM") == "offscreen"

if qt_offscreen and not modules_available("dask", notify=False):

    print("Please pip install 'dask' before converting series to zarr.")
    sys.exit()

t_convert = datetime.now(timezone.utc)

print(f"Starting conversion...")

args = get_args()

jser_fp, output_zarr, start, end, mag, padding, max_tissue, labels_only = parse_args(args)

print_flush("Opening series...")

series = stdout_to_devnull(Series.openJser)(jser_fp)

print_flush("Series open...")

print_flush("Gathering args...")

groups = flatten_list(args.groups) if args.groups else None

all_sections = sorted(
    list(series.sections.keys())
)

if start is None: start = all_sections[1]  # steer clear of cal grid
if end is None: end = all_sections[-1]

srange = (start, end + 1)

sections = []
for n in sorted(list(series.sections.keys())):
    if start <= n <= end:
        sections.append(n)

## The first section's mag sets the padding and, without --mag, the zarr's
## pixel size

img_mag = series.loadSection(sections[0]).mag
zarr_mag = mag if mag is not None else img_mag


def image_size(section):
    """The w and h in pixels of a section's image, or None if it is missing.

    Reads the header, not the pixels.
    """

    ## TODO: Validate Zarr container more appropriately
    if series.src_dir.endswith("zarr"):

        img_scale_1 = os.path.join(series.src_dir, "scale_1", section.src)
        try:
            h, w = zarr.open(img_scale_1, "r").shape
        except (KeyError, ValueError, AttributeError):
            return None
        return w, h

    size = QImageReader(section.src_fp).size()
    return (size.width(), size.height()) if size.isValid() else None


## Determine if req all tissue or crop

get_all = (bool(max_tissue) or not bool(groups))

padding_um = padding * img_mag  # padding is given in image pixels

## Procedures

if get_all:  # request all available tissue

    x_mins, y_mins, x_maxs, y_maxs = ([], [], [], [])

    for snum in sections:

        ## each section's own image: one size for all cropped any larger one
        section = series.loadSection(snum)
        size = image_size(section)
        if size is None:
            continue

        w, h = size
        img_corners = [
            (x * section.mag, y * section.mag)
            for x, y in [(0, 0), (w, 0), (w, h), (0, h)]
        ]
        corners_transformed = section.tform.map(img_corners)

        x_vals, y_vals = list(zip(*corners_transformed))

        x_mins.append(min(x_vals))
        y_mins.append(min(y_vals))
        
        x_maxs.append(max(x_vals))
        y_maxs.append(max(y_vals))

    if not x_mins:
        series.close()
        sys.exit("Conversion failed: no section image could be read.")

    window = [
        min(x_mins),                # x
        min(y_mins),                # y 
        max(x_maxs) - min(x_mins),  # w
        max(y_maxs) - min(y_mins),  # h
    ]

else:  # request only around group(s)

    window, _ = groupsToVolume(series, groups, padding_um)

additional_attrs = {
    
        "filepath" : str(Path(jser_fp).absolute()),
        "sha1sum"  : get_sha1sum(jser_fp),
        "date"     : t_convert.strftime("%Y-%m-%d"),
        "time"     : t_convert.strftime("%H:%M:%S")
        
    }

print_flush("Initializing pyqt...")

if not QApplication.instance():

    print_flush("Creating QApplication instance...")
    app = QApplication(sys.argv)

print_flush("Creating zarr...")

if not output_zarr:
    zarr_name = createZarrName(window)

if not labels_only:

    ## Create "raw" image dataset
    zarr_fp = seriesToZarr(
        series,
        sections,
        zarr_mag,
        window=window,
        data_fp=output_zarr,
        other_attrs=additional_attrs
    )

    if zarr_fp is None:
        series.close()
        sys.exit("Conversion failed: a section could not be exported.")

else:

    zarr_fp = output_zarr

## Add labels to zarr if groups provided
if groups:

    raw_section_bounds = [min(sections), max(sections)]

    ## labels are drawn on raw's grid, which --labels_only may have written
    ## at another --mag
    raw_mag = get_true_mag(zarr.open(str(zarr_fp), "r")["raw"])

    for group in groups:

        print_flush(f"Converting group {group} to labels...")

        window_group = groupsToVolume(
            series,
            [group],
            padding_um,
            restrict_to_sections=raw_section_bounds
        )

        if not seriesToLabels(
            series,
            zarr_fp,
            group,
            window=window_group,
            img_mag=raw_mag,
            raw_window=window
        ):
            series.close()
            sys.exit(f"Conversion failed: group {group} could not be exported.")

series.close()

## Rechunk if possible

if modules_available("dask"):

    print_flush("Rechunking datasets...")

    try:

        rechunk(zarr_fp)

    except ValueError:

        print_flush("Rechunking not possible.")

## Print summary

print_summary(series, window, start, end, zarr_mag, zarr_fp)

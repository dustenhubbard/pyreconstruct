"""Crop a series' zarr images down to one object.

Every image keeps its size. Pixels outside the object's bounds, plus a radius
in microns, are set to zero, at every scale_N level.

Run with no arguments to be asked for each value. Run with flags to skip the
questions, for example from another program:

    python crop_zarr.py --jser series.jser --object dendrite_1 --radius 2
        [--zarr images.zarr] [--out cropped.zarr] [--overwrite]

With flags, progress goes to stdout as the same "@@PROGRESS@@" lines the zarr
converter prints, and errors exit nonzero before anything is written.

The output must not be the source zarr, inside it, or a folder that holds it.
An existing output is left alone: with flags the run stops unless --overwrite
is given, and with no arguments the script asks first. A replaced output is
removed whole, so no arrays from an earlier run are left in it.
"""

import argparse
import difflib
import math
import os
import re
import shutil
import signal
import sys
import tempfile

import zarr
import numpy as np

# add src modules to the system path
sys.path.append(os.path.join(os.getcwd(), "..", ".."))
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.progress import NullProgressReporter


class CropError(Exception):
    """A problem with the inputs, found before anything is written."""


class OutputExists(CropError):
    """The output path already exists and replacing it was not asked for."""

    def __init__(self, out_fp : str):
        super().__init__(
            f"The output already exists: {out_fp!r}. Pass --overwrite to replace it."
        )
        self.out_fp = out_fp


def defaultOutput(src_dir : str, obj_name : str):
    """Return the default output path: <stem>_<obj>_crop<sep>zarr beside the source."""
    # recognize zarr directories whose "zarr" suffix uses any common
    # separator, e.g. "foo.zarr", "foo-zarr", or "foo_zarr"
    basename = os.path.basename(src_dir)
    match = re.match(r"^(?P<stem>.+)(?P<sep>[.\-_])(?P<ext>zarr)$", basename, re.IGNORECASE)
    if not match:
        raise CropError(
            f"This series does not use a zarr file for its images (src_dir={src_dir!r})."
        )

    # preserve the original separator/suffix style
    zarr_name = match.group("stem")
    zarr_sep = match.group("sep")
    zarr_ext = match.group("ext")
    return os.path.join(
        os.path.dirname(src_dir),
        f"{zarr_name}_{obj_name}_crop{zarr_sep}{zarr_ext}"
    )


def openSource(src_dir : str):
    """Open the source zarr and return (group, sorted scale factors)."""
    if not os.path.isdir(src_dir):
        raise CropError(f"Zarr not found: {src_dir!r}")
    try:
        src_group = zarr.open_group(src_dir, mode="r")
    except Exception:
        raise CropError(f"Not a zarr: {src_dir!r}")

    # the images live under scale_N groups (multiscale zarr); discover them
    scales = sorted(
        int(name.split("_")[1])
        for name in src_group.group_keys()
        if name.startswith("scale_") and name.split("_")[1].isnumeric()
    )
    if not scales:
        raise CropError(f"No scale_N groups found in {src_dir!r}.")
    return src_group, scales


def isWithin(path : str, folder : str):
    """True if path is folder or anywhere under it.

    Symlinks in path are resolved first, and each of its folders is compared
    with os.path.samefile, so a link, a different letter case on a
    case-insensitive disk or another alias for folder still counts.
    """
    if not os.path.exists(folder):
        return False
    current = os.path.realpath(path)
    while True:
        if os.path.exists(current) and os.path.samefile(current, folder):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def isZarr(path : str):
    """True if path is a zarr directory (not a link to one)."""
    return (
        os.path.isdir(path)
        and not os.path.islink(path)
        and any(os.path.isfile(os.path.join(path, name)) for name in (".zgroup", ".zarray", "zarr.json"))
    )


def resolvePaths(series : Series, obj_name : str, src_dir : str = "", out_fp : str = "", overwrite : bool = False):
    """Check the source and output and return (out_fp, src_group, scales).

    Nothing is written here. With overwrite, an existing output is allowed
    only if it is a zarr; replaceOutput removes it once every check passes.
    """
    # use the override if given, otherwise the location stored in the series
    src_dir = (src_dir or series.src_dir).rstrip("/\\")  # normalize trailing separators
    out_fp = out_fp.rstrip("/\\") if out_fp else defaultOutput(src_dir, obj_name)
    src_group, scales = openSource(src_dir)

    # writing inside the source would change it, and replacing a folder
    # that holds the source would delete it
    if isWithin(out_fp, src_dir):
        raise CropError(f"The output path is the source zarr or inside it: {out_fp!r}")
    if isWithin(src_dir, out_fp):
        raise CropError(f"The output path holds the source zarr: {out_fp!r}")

    if os.path.lexists(out_fp):
        if not overwrite:
            raise OutputExists(out_fp)
        if not isZarr(out_fp):
            raise CropError(f"The output path exists and is not a zarr, so it is not replaced: {out_fp!r}")
    return out_fp, src_group, scales


def replaceOutput(out_fp : str):
    """Remove an existing output zarr so the crop starts from an empty store.

    Only a zarr directory is removed; resolvePaths has already refused
    anything else, and an output that overlaps the source.
    """
    if isZarr(out_fp):
        shutil.rmtree(out_fp)


def checkObject(series : Series, obj_name : str):
    """Raise if the object is not in the series, listing close matches."""
    names = list(series.data["objects"])
    if obj_name in names:
        return
    message = f"Object {obj_name!r} is not in this series."
    matches = difflib.get_close_matches(obj_name, names, n=5)
    if matches:
        message += " Close matches: " + ", ".join(matches)
    raise CropError(message)


def pixelWindow(bounds : tuple, radius : float, mag : float, shape : tuple):
    """Return the (top, bottom, left, right) pixel rows and columns to keep.

        Params:
            bounds (tuple): (xmin, ymin, xmax, ymax) in microns, y up from the
                bottom of the image
            radius (float): microns to add on every side
            mag (float): microns per pixel at this scale level
            shape (tuple): the image (rows, columns)
        Returns:
            (tuple): top, bottom, left, right, each clamped to the image, so a
                window wholly outside it is empty rather than wrapping around
                from the far edge as a negative index would
    """
    xmin, ymin, xmax, ymax = bounds
    height, width = shape[0], shape[1]

    def clamp(value, limit):
        return min(max(value, 0), limit)

    left = clamp(round((xmin - radius) / mag), width)
    right = clamp(round((xmax + radius) / mag), width)
    top = clamp(round(height - (ymax + radius) / mag), height)
    bottom = clamp(round(height - (ymin - radius) / mag), height)
    return top, bottom, left, right


def cropSections(
        series : Series,
        obj_name : str,
        radius : float,
        src_group,
        scales : list,
        new_zarr_fp : str,
        show_progress : bool = True,
        report : bool = False):
    """Write the cropped images for every section into new_zarr_fp.

        Params:
            report (bool): print progress lines to stdout for a wrapper program
    """
    # "w-" refuses a store that is already there: replaceOutput has removed
    # any earlier output, so nothing from it can mix with this run
    new_group = zarr.open_group(new_zarr_fp, mode="w-")

    total = len(series.sections)
    if report:
        print(f"@@PROGRESS@@ TOTAL {total}", flush=True)

    # iterate through the sections
    for done, (snum, section) in enumerate(series.enumerateSections(
        show_progress=show_progress, message="Cropping images..."
    ), start=1):
        # the section bounds are in microns; section.mag is the scale_1 resolution
        if obj_name in section.contours:
            bounds = section.contours[obj_name].getBounds()
        else:
            bounds = None  # blank image on this section

        # crop the image at every scale level
        for scale in scales:
            scale_grp = f"scale_{scale}"
            if section.src not in src_group[scale_grp]:
                continue
            image = src_group[scale_grp][section.src]
            cropped = np.zeros(image.shape, dtype=image.dtype)

            if bounds is not None:
                # resolution of this scale level (scale_1 mag scaled by factor)
                mag = section.mag * scale
                t, b, l, r = pixelWindow(bounds, radius, mag, image.shape)
                cropped[t:b, l:r] = image[t:b, l:r]

            # Same shape as the source, so traces line up with the full zarr.
            # Chunks that are all zero are not stored. A missing chunk reads
            # as fill_value 0, so the pixels are the same and a mostly black
            # crop writes far fewer files.
            out = new_group.require_group(scale_grp)
            out.create_dataset(
                section.src,
                data=cropped,
                chunks=image.chunks,
                dtype=image.dtype,
                fill_value=0,
                write_empty_chunks=False,
                overwrite=True,
            )

        if report:
            print(f"Cropped section {snum}", flush=True)
            print(f"@@PROGRESS@@ STEP {done} {total}", flush=True)


def cropZarr(series_fp : str, obj_name : str, radius : float, src_dir : str = "", out_fp : str = "", overwrite : bool = False):
    """Crop the zarr file for a series.

        Params:
            series_fp (str): the filepath for the series jser
            obj_name (str): the name of the object to crop around
            radius (float): the radius of the crop
            src_dir (str): optional path to the source zarr; if blank, the
                location stored in the series is used. An override must point
                to the same zarr (same scale_N groups and per-section array
                names), just at a different location.
            out_fp (str): optional output zarr path; if blank,
                <stem>_<obj>_crop<sep>zarr next to the source
            overwrite (bool): replace an existing output zarr; if False, an
                existing output raises OutputExists
        Returns:
            (str): the output zarr path
    """
    series = Series.openJser(series_fp)
    if series is None:
        raise CropError(f"Could not open {series_fp!r}.")
    try:
        out_fp, src_group, scales = resolvePaths(series, obj_name, src_dir, out_fp, overwrite)
        replaceOutput(out_fp)
        cropSections(series, obj_name, radius, src_group, scales, out_fp)
    finally:
        series.close()
    return out_fp


def radiusArg(value : str):
    """Parse the radius: a finite number of microns, zero or more."""
    try:
        radius = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}")
    if not math.isfinite(radius) or radius < 0:
        raise argparse.ArgumentTypeError(f"must be zero or more: {value!r}")
    return radius


def parseArgs(argv : list):
    parser = argparse.ArgumentParser(
        description="Crop a series' zarr images to one object. "
        "Run with no arguments to be asked for each value."
    )
    parser.add_argument("--jser", help="the series .jser file")
    parser.add_argument("--object", help="the object to crop around")
    parser.add_argument("--radius", type=radiusArg,
                        help="microns to keep around the object's bounds")
    parser.add_argument("--zarr", default="",
                        help="the source zarr (default: the location stored in the series)")
    parser.add_argument("--out", default="",
                        help="the output zarr (default: <stem>_<object>_crop.zarr, -zarr or _zarr beside the source, matching it)")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace the output zarr if it exists (default: stop)")
    args = parser.parse_args(argv)

    missing = [
        flag for flag, value in
        (("--jser", args.jser), ("--object", args.object), ("--radius", args.radius))
        if value is None
    ]
    if missing:
        parser.error("missing " + ", ".join(missing))
    return args


def raiseSystemExit(signum, frame):
    """Turn SIGTERM into SystemExit so the cleanup in runCli runs."""
    sys.exit(128 + signum)


def runCli(args):
    """Crop without prompts or dialogs. Returns the output zarr path."""
    signal.signal(signal.SIGTERM, raiseSystemExit)

    if not os.path.isfile(args.jser):
        raise CropError(f"Jser not found: {args.jser!r}")

    # Open a copy of the jser in a new temp folder. openJser unpacks a series
    # into a hidden .<name> folder beside the file, and a run killed partway
    # would leave that folder next to the real jser, where PyReconstruct later
    # offers to recover it as unsaved work. Here it is removed with the temp
    # folder. This also means the crop always reads the saved file: when the
    # series is open in PyReconstruct, opening the original would load that
    # session's unsaved working state instead.
    tmp_dir = tempfile.mkdtemp(prefix="crop_zarr_")
    try:
        copy_fp = os.path.join(tmp_dir, os.path.basename(args.jser))
        shutil.copyfile(args.jser, copy_fp)
        series = Series.openJser(copy_fp, progress=NullProgressReporter)
        if series is None:
            raise CropError(f"Could not open {args.jser!r}.")
        series.setProgressReporter(NullProgressReporter)

        checkObject(series, args.object)
        out_fp, src_group, scales = resolvePaths(
            series, args.object, args.zarr, args.out, args.overwrite
        )
        replaceOutput(out_fp)
        cropSections(
            series, args.object, args.radius, src_group, scales, out_fp,
            show_progress=False, report=True,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Crop complete: {out_fp}", flush=True)
    return out_fp


def main(argv : list):
    if not argv:
        jser_fp = input("Jser filepath: ")
        obj_name = input("Object name to crop around: ")
        radius = float(input("Radius around BOUNDARY of object to include: "))
        src_dir = input("Zarr location (leave blank to use the location stored in the series): ").strip()

        try:
            cropZarr(jser_fp, obj_name, radius, src_dir)
        except OutputExists as e:
            answer = input(f"{e.out_fp} already exists. Replace it? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Not replaced.")
                return 1
            cropZarr(jser_fp, obj_name, radius, src_dir, overwrite=True)
        return 0

    args = parseArgs(argv)
    try:
        runCli(args)
    except CropError as e:
        print(f"error: {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

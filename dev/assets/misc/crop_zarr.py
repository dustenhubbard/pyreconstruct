"""Crop a series' zarr images down to one object.

Every image keeps its size. Pixels outside the object's bounds, plus a radius
in microns, are set to zero, at every scale_N level.

Run with no arguments to be asked for each value. Run with flags to skip the
questions, for example from another program:

    python crop_zarr.py --jser series.jser --object dendrite_1 --radius 2
        [--zarr images.zarr] [--out cropped.zarr]

With flags, progress goes to stdout as the same "@@PROGRESS@@" lines the zarr
converter prints, and errors exit nonzero before anything is written.

Four gaps in the data are handled, each on by default with a flag to turn
it off:
- A section without the object keeps its image inside the window of the
  nearest section with the object (ties go to the earlier section), instead
  of coming out black. --blank-untraced leaves it black.
- A section whose image is not in the zarr gets an image the size of the
  nearest section with the object, 128 gray inside that section's window and
  0 outside it, so the crop has an image for every section. --skip-missing
  writes no image for it.
- When no image name in the series is in the zarr, each section is matched
  to the zarr image whose name starts with its section number, only if every
  zarr image name starts with a number and those numbers are exactly the
  series' section numbers, one image each. The crop names its images as the
  series does. --exact-names turns the matching off.
- A section that has an image but where no window keeps any of its pixels
  keeps its full, uncropped image instead of coming out black. That is when
  the object's window is outside the image, the borrowed window of the
  nearest section is outside this image, the mag or trace is not a usable
  number, or there is no section to borrow a window from. --blank-failed
  leaves it black. A crop where no section with the object keeps pixels is
  still an error, below.

Every run writes crop_log.txt inside the output zarr: the inputs, a summary,
and each section that was filled, made gray, kept whole or matched by
number. The summary is printed too.

A crop that would keep no pixels is an error too, found before the output
folder is made: when no section's image name is in the zarr and the names
cannot be matched by section number (the series and the zarr do not belong
together), or when the object is inside no section image.

The output must be a new path: not one that exists, not a drive or file
system root, and not the source zarr, inside it, or a folder that holds it.
Neither path may have a "." or ".." part after a folder name; "./" and "../"
at the start are fine.
The script never deletes anything; remove an old output yourself to reuse
its name. That includes the partial output a stopped run leaves behind.
"""

import argparse
import datetime
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


## the log's file name, inside the output zarr
LOG_NAME = "crop_log.txt"
## the value written inside the window for a section whose image is missing
GRAY = 128


class CropError(Exception):
    """A problem with the inputs, found before anything is written."""


def outputExists(out_fp : str):
    return CropError(
        f"The output already exists: {out_fp!r}. Remove it or choose another path."
    )


def trimSeparators(path : str, pathmod=os.path):
    """Drop trailing separators, but keep a root such as / or C:\\ whole.

    Trimming a root would change what it names: "/" would become "" (the
    current folder) and "C:\\" the drive-relative "C:".
    """
    trimmed = path.rstrip("/\\")
    if trimmed in ("", pathmod.splitdrive(path)[0]):
        return path
    return trimmed


def checkPlainPath(path : str, what : str):
    """Raise if path has a "." or ".." part after a named part.

    After a name that may be a link, "." and ".." mean different folders to
    the file system and to zarr, which collapses them as text, and a link to
    a missing folder given as "link/." would not count as existing. Leading
    "./" and "../" are kept: they start from the current folder, which is
    already a real path, so both read them the same way.
    """
    seps = os.sep + (os.altsep or "")
    named = False
    for part in re.split(f"[{re.escape(seps)}]+", path):
        if part in (".", ".."):
            if named:
                raise CropError(f"Use a {what} path without . or .. parts: {path!r}")
        elif part:
            named = True


def isRoot(path : str):
    """True if path is a drive or file system root, after resolving links."""
    real = os.path.realpath(path)
    return os.path.dirname(real) == real


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


def resolvePaths(series : Series, obj_name : str, src_dir : str = "", out_fp : str = ""):
    """Check the source and output and return (out_fp, src_group, scales).

    A "." or ".." after a folder name is refused (checkPlainPath). Both
    paths are then resolved once, links included, and every check, read and
    write uses the resolved path.
    Nothing is written here. cropSections creates the output folder itself,
    in one step that fails if anything got there first.
    """
    # use the override if given, otherwise the location stored in the series
    src_dir = trimSeparators(src_dir or series.src_dir)
    out_fp = trimSeparators(out_fp) if out_fp else defaultOutput(src_dir, obj_name)
    checkPlainPath(src_dir, "source")
    checkPlainPath(out_fp, "output")
    given_out = out_fp
    src_dir = os.path.realpath(src_dir)
    out_fp = os.path.realpath(out_fp)
    src_group, scales = openSource(src_dir)

    if isRoot(out_fp):
        raise CropError(f"The output path is a drive or file system root: {out_fp!r}")
    # writing inside the source would change it
    if isWithin(out_fp, src_dir):
        raise CropError(f"The output path is the source zarr or inside it: {out_fp!r}")
    if isWithin(src_dir, out_fp):
        raise CropError(f"The output path holds the source zarr: {out_fp!r}")
    # the entry as given must be new too: a link to a missing folder exists,
    # though resolving it names the missing folder
    if os.path.lexists(given_out):
        raise outputExists(given_out)
    if os.path.lexists(out_fp):
        raise outputExists(out_fp)
    return out_fp, src_group, scales


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


def someNames(names : list, limit : int = 3):
    """The first few names, quoted, for an error message."""
    shown = ", ".join(repr(name) for name in names[:limit])
    return shown + ", ..." if len(names) > limit else shown


def spans(numbers, limit : int = 0):
    """Section numbers as runs, e.g. "0-24, 220, 289-317"; with a limit, the first few."""
    runs = []
    for number in sorted(numbers):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    text = [f"{first}-{last}" if last > first else f"{first}" for first, last in runs]
    if limit and len(text) > limit:
        return ", ".join(text[:limit]) + ", ..."
    return ", ".join(text)


def plural(count : int, word : str):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def matchByNumber(sections : dict, scales : list, groups : list):
    """Match each section to the zarr image whose name starts with its number.

    Some zarrs name their images "000_<code>_grid000.tif" while the series
    names them "<code>_000.tif". The match is a guess about how the zarr was
    named, so it is made only when nothing about it is ambiguous: every scale
    group holds the same names, every name starts with a number, no two names
    start with the same number, those numbers are exactly the series' section
    numbers (so an offset, a missing image or an extra one is refused), and no
    two sections use the same image name, since the crop names its images as
    the series does.

        Returns:
            (tuple): ({section number: zarr image name}, "") or (None, the reason
                there is no match)
    """
    names = sorted(groups[0].array_keys())
    for scale, group in zip(scales[1:], groups[1:]):
        if sorted(group.array_keys()) != names:
            return None, f"scale_{scale} holds other image names than scale_{scales[0]}"
    by_number = {}
    for name in names:
        match = re.match(r"\d+", name)
        if not match:
            return None, f"{name!r} does not start with a number"
        number = int(match.group())
        if number in by_number:
            return None, f"{by_number[number]!r} and {name!r} start with the same number"
        by_number[number] = name
    if set(by_number) != set(sections):
        return None, (
            f"the zarr's {plural(len(by_number), 'image')} start with "
            f"{spans(by_number, 4) or 'no numbers'}, and the series' "
            f"{plural(len(sections), 'section')} are {spans(sections, 4)}"
        )
    seen = set()
    for data in sections.values():
        if data["src"] in seen:
            return None, f"two sections in the series use the image name {data['src']!r}"
        seen.add(data["src"])
    return {snum: by_number[snum] for snum in sections}, ""


def matchImageNames(series : Series, scales : list, groups : list, by_number : bool = True):
    """Return ({section number: its image's name in the zarr}, matched by number).

    The series' own names are used when any of them is in the zarr; a section
    whose name is not there is then a missing image. Otherwise the names come
    from matchByNumber, and with no match the crop would keep nothing, so it
    is an error.
    """
    sections = series.data["sections"]
    if any(data["src"] in group for data in sections.values() for group in groups):
        return {snum: data["src"] for snum, data in sections.items()}, False
    reason = "--exact-names is set"
    if by_number:
        names, reason = matchByNumber(sections, scales, groups)
        if names:
            return names, True
    series_names = [sections[snum]["src"] for snum in sorted(sections)]
    zarr_names = sorted(groups[0].array_keys())
    raise CropError(
        f"No section image in this series is in the zarr. "
        f"The series names {someNames(series_names)}; "
        f"the zarr's scale_{scales[0]} has {someNames(zarr_names) or 'no images'}. "
        f"They cannot be matched by section number: {reason}. "
        f"Check that the zarr was made for this series."
    )


def usableWindow(bounds : tuple, radius : float, mag : float, shape : tuple):
    """pixelWindow, or None when it would keep no pixels of the image.

    That is when the window is wholly outside the image, or when the bounds
    or the mag are not finite numbers, or the mag is not above zero (a bad
    calibration), where pixelWindow itself would fail.
    """
    if not (math.isfinite(mag) and mag > 0 and all(math.isfinite(v) for v in bounds)):
        return None
    t, b, l, r = pixelWindow(bounds, radius, mag, shape)
    return (t, b, l, r) if b > t and r > l else None


def checkPixelsKept(obj_name : str, radius : float, scales : list, groups : list, names : dict, traced : dict):
    """Return the sections whose own window keeps pixels; raise if there are none.

    A section keeps pixels when the object is on it, its image is in the zarr,
    and the object's window is not empty at some scale level. Filled, gray and
    full-image sections are not counted: a crop with none of these would be
    a copy of the zarr, which means the series and the zarr do not belong
    together. Reads only array shapes, never pixels.
    """
    usable = set()
    for snum, (bounds, mag) in traced.items():
        for scale, group in zip(scales, groups):
            if names[snum] in group and usableWindow(
                    bounds, radius, mag * scale, group[names[snum]].shape):
                usable.add(snum)
                break
    if not usable:
        raise CropError(
            f"The crop would be empty: {obj_name!r} is inside no section image in the zarr."
        )
    return usable


class CropPlan:
    """What cropSections writes for each section, worked out before it writes.

        Attributes:
            names (dict): section number: its image's name in the zarr
            by_number (bool): True if names were matched by section number
            traced (dict): section number: (bounds, mag) of the object, for
                every section with the object
            missing (dict): section number: the scale factors whose group
                lacks its image, for every section missing one
            untraced (list): sections without the object that have an image
                at some scale level
            neighbor (dict): section number: the nearest section with the
                object, a window that keeps pixels and its image at every
                scale level (ties go to the earlier one), for every section
                without the object or missing an image; None when no section
                qualifies
            windows (dict): section number: {scale: the window to keep, or
                None}, for every scale level that has the section's image
            failed (dict): section number: why no window keeps any of its
                pixels, for every section that would come out black though
                it has an image and was meant to keep part of it
            fill (bool): fill sections without the object
            gray (bool): write gray images for missing ones
            full (bool): keep the whole image of a failed section
    """

    def __init__(self, **attributes):
        self.__dict__.update(attributes)


def planCrop(
        series : Series,
        obj_name : str,
        radius : float,
        src_group,
        scales : list,
        fill_untraced : bool = True,
        gray_missing : bool = True,
        match_by_number : bool = True,
        full_on_fail : bool = True):
    """Match the image names and choose each section's window; raise a
    CropError when the crop cannot be made. Reads only array shapes."""
    groups = [src_group[f"scale_{scale}"] for scale in scales]
    names, by_number = matchImageNames(series, scales, groups, match_by_number)

    traced = {}
    snums = sorted(series.getObjectSections([obj_name]))
    for snum, section in series.enumerateSections(show_progress=False, section_numbers=snums):
        if obj_name in section.contours:
            traced[snum] = (section.contours[obj_name].getBounds(), section.mag)
    usable = checkPixelsKept(obj_name, radius, scales, groups, names, traced)

    sections = series.data["sections"]
    snums = sorted(sections)
    missing = {}
    for snum in snums:
        absent = [scale for scale, group in zip(scales, groups) if names[snum] not in group]
        if absent:
            missing[snum] = absent
    untraced = [
        snum for snum in snums
        if snum not in traced and len(missing.get(snum, ())) < len(scales)
    ]
    whole = [snum for snum in sorted(usable) if snum not in missing]
    neighbor = {
        snum: min(whole, key=lambda k: (abs(k - snum), k)) if whole else None
        for snum in snums
        if snum not in traced or snum in missing
    }

    windows, failed = {}, {}
    for snum in snums:
        present = [(scale, group) for scale, group in zip(scales, groups) if names[snum] in group]
        if not present:
            continue
        nearest = neighbor.get(snum)
        if snum in traced:
            bounds, mag = traced[snum]
            numbers = math.isfinite(mag) and mag > 0 and all(math.isfinite(v) for v in bounds)
            reason = ("its trace's window is outside its image" if numbers else
                      "its magnification or trace is not a usable number (a mag of 0, for example)")
        elif not fill_untraced:
            windows[snum] = {scale: None for scale, _ in present}  # black on purpose
            continue
        elif nearest is None:
            windows[snum] = {scale: None for scale, _ in present}
            failed[snum] = (f"no section with {obj_name} has a window that keeps pixels "
                            f"and its image at every scale level")
            continue
        else:
            bounds, mag = traced[nearest][0], sections[snum]["mag"]
            reason = f"the window of section {nearest} is outside its image"
        windows[snum] = {
            scale: usableWindow(bounds, radius, mag * scale, group[names[snum]].shape)
            for scale, group in present
        }
        if not any(windows[snum].values()):
            failed[snum] = reason
    return CropPlan(
        names=names, by_number=by_number, traced=traced, missing=missing,
        untraced=untraced, neighbor=neighbor, windows=windows, failed=failed,
        fill=fill_untraced, gray=gray_missing, full=full_on_fail,
    )


def describeCrop(plan : CropPlan, series : Series, obj_name : str, radius : float, scales : list, about : list):
    """Return (the summary lines, the whole log text).

        Params:
            about (list): (label, value) pairs for the log's header
    """
    sections = series.data["sections"]
    nearest = f"the nearest section with {obj_name}"
    no_reference = (f"no section with {obj_name} has a window that keeps pixels "
                    f"and its image at every scale level")
    cropped = [snum for snum in plan.traced if snum not in plan.missing and snum not in plan.failed]
    summary = [f"Cropped around {obj_name}: {len(cropped)} of {plural(len(sections), 'section')}."]
    details = []

    if plan.by_number:
        first = min(sections)
        summary.append(
            f"Image names: no series name is in the zarr, so each section uses the "
            f"zarr image whose name starts with its section number ({plan.names[first]!r} "
            f"is section {first}). The crop uses the series' names ({sections[first]['src']!r}, ...)."
        )
        details += ["", "Image names (section: zarr image -> crop image)"]
        details += [
            f"  {snum}: {plan.names[snum]} -> {sections[snum]['src']}" for snum in sorted(sections)
        ]

    if not plan.fill and plan.untraced:
        summary.append(
            f"No {obj_name} on {plural(len(plan.untraced), 'section')} "
            f"({spans(plan.untraced)}): left black (--blank-untraced)."
        )
    filled = [snum for snum in plan.untraced if plan.fill and snum not in plan.failed]
    if filled:
        summary.append(
            f"No {obj_name} on {plural(len(filled), 'section')} ({spans(filled)}): "
            f"each keeps its image inside the window of {nearest}."
        )
        details += ["", f"Sections without {obj_name} (section: the section whose window it kept)"]
        details += [f"  {snum}: {plan.neighbor[snum]}" for snum in filled]

    if plan.failed:
        head = (f"No usable window on {plural(len(plan.failed), 'section')} "
                f"({spans(plan.failed)})")
        if plan.full:
            summary.append(f"{head}: each keeps its full, uncropped image.")
            details += ["", "Sections that kept the full image (section: why no window kept pixels)"]
        else:
            summary.append(f"{head}: left black (--blank-failed).")
            details += ["", "Sections left black with no usable window (section: why)"]
        details += [f"  {snum}: {reason}" for snum, reason in sorted(plan.failed.items())]

    if plan.missing:
        head = f"No image in the zarr for {plural(len(plan.missing), 'section')} ({spans(plan.missing)})"
        if not plan.gray:
            summary.append(f"{head}: left out of the crop (--skip-missing).")
        elif plan.neighbor[min(plan.missing)] is None:
            summary.append(f"{head}: left out of the crop, because {no_reference}.")
        else:
            summary.append(
                f"{head}: {GRAY} gray inside the window of {nearest}, at that section's image size."
            )
            details += ["", "Sections with no image in the zarr "
                            "(section, series image name: the section whose window and size it used)"]
            for snum, absent in sorted(plan.missing.items()):
                only = ""
                if len(absent) < len(scales):
                    only = " (" + ", ".join(f"scale_{scale}" for scale in absent) + " only)"
                details.append(f"  {snum} {sections[snum]['src']}: {plan.neighbor[snum]}{only}")

    if len(summary) == 1:
        summary.append(f"Every section has {obj_name} and its image in the zarr.")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = [
        f"crop_zarr.py log, written {stamp}",
        "",
        *(f"{label}: {value}" for label, value in about),
        f"Object: {obj_name}",
        f"Radius: {radius:g} microns",
        "Scale levels: " + ", ".join(str(scale) for scale in scales),
        "",
        "Summary",
    ]
    return summary, "\n".join(header + summary + details) + "\n"


def writeImage(new_group, scale_grp : str, name : str, data, like):
    """Write one output image with the chunks and type of the zarr image like."""
    # Same shape as the source, so traces line up with the full zarr.
    # For integer and bool images, chunks that are all zero are not
    # stored. A missing chunk reads as fill_value 0, so the pixels are
    # the same and a mostly black crop writes far fewer files. Float
    # images store every chunk: zarr counts a chunk of -0.0 as equal
    # to the fill value, and skipping it would read back as +0.0.
    new_group.require_group(scale_grp).create_dataset(
        name,
        data=data,
        chunks=like.chunks,
        dtype=like.dtype,
        fill_value=0,
        write_empty_chunks=like.dtype.kind not in "biu",
        overwrite=True,
    )


def cropSections(
        series : Series,
        obj_name : str,
        radius : float,
        src_group,
        scales : list,
        new_zarr_fp : str,
        show_progress : bool = True,
        report : bool = False,
        fill_untraced : bool = True,
        gray_missing : bool = True,
        match_by_number : bool = True,
        full_on_fail : bool = True,
        jser_fp : str = ""):
    """Write the cropped images for every section, and the log, into new_zarr_fp.

        Params:
            report (bool): print progress lines to stdout for a wrapper program
            fill_untraced, gray_missing, match_by_number, full_on_fail (bool):
                see planCrop
            jser_fp (str): the series file named in the log
        Returns:
            (str): the log's path
    """
    # Make the output folder in one step that fails if the path exists, so
    # an output another program made after resolvePaths checked is never
    # written into. Its parent folders may be new. The path is resolved so
    # that mkdir and zarr name the same folder.
    checkPlainPath(new_zarr_fp, "output")
    if os.path.lexists(new_zarr_fp):
        raise outputExists(new_zarr_fp)
    plan = planCrop(series, obj_name, radius, src_group, scales,
                    fill_untraced, gray_missing, match_by_number, full_on_fail)
    new_zarr_fp = os.path.realpath(new_zarr_fp)
    parent = os.path.dirname(new_zarr_fp)
    os.makedirs(parent, exist_ok=True)
    try:
        os.mkdir(new_zarr_fp)
    except FileExistsError:
        raise outputExists(new_zarr_fp)
    new_group = zarr.open_group(new_zarr_fp, mode="w-")

    total = len(series.sections)
    if report:
        print(f"@@PROGRESS@@ TOTAL {total}", flush=True)

    # iterate through the sections
    for done, (snum, section) in enumerate(series.enumerateSections(
        show_progress=show_progress, message="Cropping images..."
    ), start=1):
        name = plan.names[snum]
        nearest = plan.neighbor.get(snum)

        # crop the image at every scale level; the output keeps the series' name
        for scale in scales:
            scale_grp = f"scale_{scale}"
            group = src_group[scale_grp]
            if name in group:
                image = group[name]
                if snum in plan.failed and plan.full:
                    # no window keeps any pixels here: keep the whole image
                    writeImage(new_group, scale_grp, section.src, image[:], image)
                    continue
                cropped = np.zeros(image.shape, dtype=image.dtype)
                # the window of the object here, or of the nearest section with it
                window = plan.windows[snum][scale]
                if window is not None:
                    t, b, l, r = window
                    cropped[t:b, l:r] = image[t:b, l:r]
                writeImage(new_group, scale_grp, section.src, cropped, image)
            elif plan.gray and nearest is not None:
                # no image: gray in the nearest section's window, at its size
                like = group[plan.names[nearest]]
                bounds, mag = plan.traced[nearest]
                gray = np.zeros(like.shape, dtype=like.dtype)
                window = usableWindow(bounds, radius, mag * scale, like.shape)
                if window is not None:
                    t, b, l, r = window
                    gray[t:b, l:r] = GRAY
                writeImage(new_group, scale_grp, section.src, gray, like)

        if report:
            print(f"Cropped section {snum}", flush=True)
            print(f"@@PROGRESS@@ STEP {done} {total}", flush=True)

    # written last, so a log in the output means the crop finished
    about = [("Series", jser_fp or series.jser_fp),
             ("Source zarr", getattr(src_group.store, "path", "")),
             ("Output zarr", new_zarr_fp)]
    summary, text = describeCrop(plan, series, obj_name, radius, scales, about)
    log_fp = os.path.join(new_zarr_fp, LOG_NAME)
    with open(log_fp, "w", encoding="utf-8") as log:
        log.write(text)
    for line in summary:
        print(line, flush=True)
    print(f"Log: {log_fp}", flush=True)
    return log_fp


def cropZarr(
        series_fp : str,
        obj_name : str,
        radius : float,
        src_dir : str = "",
        out_fp : str = "",
        fill_untraced : bool = True,
        gray_missing : bool = True,
        match_by_number : bool = True,
        full_on_fail : bool = True):
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
            fill_untraced, gray_missing, match_by_number, full_on_fail
                (bool): see the module docstring; each is on unless turned off
        Returns:
            (str): the output zarr path
    """
    series = Series.openJser(series_fp)
    if series is None:
        raise CropError(f"Could not open {series_fp!r}.")
    try:
        checkObject(series, obj_name)
        out_fp, src_group, scales = resolvePaths(series, obj_name, src_dir, out_fp)
        cropSections(
            series, obj_name, radius, src_group, scales, out_fp,
            fill_untraced=fill_untraced, gray_missing=gray_missing,
            match_by_number=match_by_number, full_on_fail=full_on_fail,
            jser_fp=os.path.realpath(series_fp),
        )
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
    parser.add_argument("--blank-untraced", action="store_true",
                        help="leave sections without the object black, instead of keeping "
                        "their image inside the nearest traced section's window")
    parser.add_argument("--skip-missing", action="store_true",
                        help="write no image for a section whose image is not in the zarr, "
                        f"instead of {GRAY} gray in the nearest traced section's window")
    parser.add_argument("--exact-names", action="store_true",
                        help="when no image name in the series is in the zarr, stop, instead "
                        "of matching images by the section number their zarr names start with")
    parser.add_argument("--blank-failed", action="store_true",
                        help="leave a section black when no window keeps any of its pixels, "
                        "instead of keeping its full, uncropped image")
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
        out_fp, src_group, scales = resolvePaths(series, args.object, args.zarr, args.out)
        cropSections(
            series, args.object, args.radius, src_group, scales, out_fp,
            show_progress=False, report=True,
            fill_untraced=not args.blank_untraced,
            gray_missing=not args.skip_missing,
            match_by_number=not args.exact_names,
            full_on_fail=not args.blank_failed,
            jser_fp=os.path.realpath(args.jser),
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
        except CropError as e:
            print(f"error: {e}", file=sys.stderr, flush=True)
            return 1
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

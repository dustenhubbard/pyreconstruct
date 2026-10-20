"""Crop a series' zarr images down to one object.

Every image keeps its size. Pixels outside the object's bounds, plus a radius
in microns, are set to zero, at every scale_N level. The crop is written to a
new zarr; the source zarr and the series are never changed.

This is the crop itself, with no prompts and no Qt. Two callers run it:
dev/assets/misc/crop_zarr.py from the command line, and the dialog under
`Series > Images` in PyReconstruct (gui/dialog/crop_zarr.py), on a worker
thread. Both check the inputs with checkObject and resolvePaths before
anything is written, and both run cropSections, which plans every section
first (planCrop), writes the images, and writes the log last.

Five gaps in the data are handled, each on by default with a flag to turn
it off:
- A section without the object keeps its image inside the window of the
  nearest section with the object (ties go to the earlier section), instead
  of coming out black (fill_untraced).
- A section whose image is not in the zarr gets an image the size of the
  nearest section with the object, mid-gray inside that section's window and
  0 outside it, so the crop has an image for every section. Mid-gray is half
  the range of an unsigned image type: 128 for 8-bit images, 32768 for
  16-bit. Signed, float and bool images have no fixed black and white, so a
  missing image there stops the crop before it writes anything
  (gray_missing).
- A section with the object whose image is all 0 under it at the first scale
  level (the zarr stored no data there) is written like a missing image:
  mid-gray in the nearest other section's window. It never lends its window
  to other sections (check_blank).
- When no image name in the series is in the zarr, each section is matched
  to the zarr image with the same number as the section's own image name,
  taking the first or the last number in the names (matchByNumber). Only
  an exact match is used: one image per section, no number twice, the same
  names at every scale level, and every image name numbered as its section
  (a reordered series is refused). The crop names its images as the series
  does (match_by_number).
- A section that has an image but where no window keeps any of its pixels
  keeps its full, uncropped image instead of coming out black. That is when
  the object's window is outside the image, the borrowed window of the
  nearest section is outside this image, the mag or trace is not a usable
  number, or there is no section to borrow a window from (full_on_fail). A
  crop where no section with the object keeps pixels is still an error,
  below.

Every run writes crop_log.txt inside the output zarr: which tool made it
(the Tool line), the inputs, a summary, and each section that was filled,
made gray, kept whole or matched by number. The log is written last, so a
log in the output means the crop finished.

A crop that would keep no pixels is an error too, found before the output
folder is made: when no section's image name is in the zarr and the names
cannot be matched by number (the series and the zarr do not belong
together), or when the object is inside no section image.

The output must be a new path: not one that exists, not a drive or file
system root, and not the source zarr, inside it, or a folder that holds it.
Neither path may have a "." or ".." part after a folder name; "./" and "../"
at the start are fine.
Nothing here deletes anything; remove an old output yourself to reuse
its name. That includes the partial output a stopped run leaves behind.
"""

import datetime
import difflib
import math
import os
import re

import zarr
import numpy as np

from PyReconstruct.modules.constants import EXPORT_ERRORS
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.image_name_match import (
    matchByNumber, plural, someNames, spans,
)


## the log's file name, inside the output zarr
LOG_NAME = "crop_log.txt"


def midGray(dtype):
    """The gray for a missing image's stand-in: half the range of an unsigned
    integer type (128 for uint8), or None for a type with no fixed black and
    white (signed, float, bool), where any value would be a guess."""
    dtype = np.dtype(dtype)
    if dtype.kind != "u":
        return None
    return (int(np.iinfo(dtype).max) + 1) // 2


class CropError(Exception):
    """A problem with the inputs, found before anything is written."""


class CropStopped(Exception):
    """The caller stopped the crop part-way (cropSections' should_stop).

    Raised before a section is written, so the sections before it are whole
    and the log is not written: a crop without a log did not finish. The
    partial output is left in place, like everything else here.

        Attributes:
            done (int): sections written before the stop
            total (int): sections in the series
            out_fp (str): the partial output
    """

    def __init__(self, done : int, total : int, out_fp : str):
        self.done, self.total, self.out_fp = done, total, out_fp
        super().__init__(
            f"The crop was stopped after {done} of {plural(total, 'section')}. "
            f"The partial output {out_fp!r} has no {LOG_NAME}; remove it to use "
            f"its name again."
        )


def appTool():
    """What this PyReconstruct is, for the log's Tool line: the version of an
    installed build, with its commit when the version file records one, or
    the branch and commit of a source checkout (constants.repo_info)."""
    from PyReconstruct.modules.constants.repo_info import repo_info
    branch, commit = repo_info["branch"], repo_info["commit"]
    if branch != "PyReconstruct":
        return f"PyReconstruct checkout {branch} ({commit})"
    try:
        from PyReconstruct._version import commit_id
    except Exception:
        commit_id = None
    return f"PyReconstruct {commit}" + (f" ({commit_id})" if commit_id else "")


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


def matchImageNames(series : Series, scales : list, groups : list, by_number : bool = True):
    """Return ({section number: its image's name in the zarr}, the number match or None).

    The series' own names are used when any of them is in the zarr; a section
    whose name is not there is then a missing image. Otherwise the names come
    from matchByNumber, held to the crop's stricter rules, since no one looks
    at the pictures: every scale group holds the same names, no two sections
    share an image name (the crop is written under them), and every section's
    image name has its section number, so a reordered series is refused
    rather than cropped over the wrong images. With no match the crop would
    keep nothing, so it is an error.
    """
    sections = series.data["sections"]
    if any(data["src"] in group for data in sections.values() for group in groups):
        return {snum: data["src"] for snum, data in sections.items()}, None
    reason = "--exact-names is set"
    if by_number:
        match, reason = sameNamesAtEveryScale(scales, groups)
        seen = set()
        for data in sections.values():
            if match and data["src"] in seen:
                match, reason = None, f"two sections in the series use the image name {data['src']!r}"
            seen.add(data["src"])
        if match:
            match, reason = matchByNumber(
                {snum: data["src"] for snum, data in sections.items()},
                sorted(groups[0].array_keys()),
            )
        if match and match["renumbered"]:
            first = match["renumbered"][0]
            reason = (
                f"the numbers in the series' image names differ from the section numbers on "
                f"{plural(len(match['renumbered']), 'section')} "
                f"({spans(match['renumbered'], 4)}; section {first} uses "
                f"{sections[first]['src']!r}), so the series may have been reordered"
            )
            match = None
        if match:
            return match["names"], match
    series_names = [sections[snum]["src"] for snum in sorted(sections)]
    zarr_names = sorted(groups[0].array_keys())
    raise CropError(
        f"No section image in this series is in the zarr. "
        f"The series names {someNames(series_names)}; "
        f"the zarr's scale_{scales[0]} has {someNames(zarr_names) or 'no images'}. "
        f"They cannot be matched by number: {reason}. "
        f"Check that the zarr was made for this series."
    )


def sameNamesAtEveryScale(scales : list, groups : list):
    """Return (True, "") if every scale group holds the same image names, else
    (False, the first group that differs)."""
    names = sorted(groups[0].array_keys())
    for scale, group in zip(scales[1:], groups[1:]):
        if sorted(group.array_keys()) != names:
            return False, f"scale_{scale} holds other image names than scale_{scales[0]}"
    return True, ""


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


def blankUnder(image, window : tuple):
    """True if every pixel of image inside window is 0.

    A zarr stores no chunk a converter left empty, and a missing chunk reads
    as 0, so an image can exist while nothing under the trace was ever
    written. Reads one chunk at a time and stops at the first nonzero one, so
    an ordinary image costs about one chunk.
    """
    t, b, l, r = window
    rows, cols = image.chunks[0], image.chunks[1]
    for top in range(t - t % rows, b, rows):
        for left in range(l - l % cols, r, cols):
            if image[max(top, t):min(top + rows, b), max(left, l):min(left + cols, r)].any():
                return False
    return True


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
            match (dict): the number match from matchByNumber, or None when
                the series' own names are in the zarr
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
            grays (list): the mid-gray values the missing images' stand-ins use
            blank (list): sections with the object whose image is all 0 under
                it at the first scale level
            grayed (list): the blank sections written as gray stand-ins
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
        full_on_fail : bool = True,
        check_blank : bool = True):
    """Match the image names and choose each section's window; raise a
    CropError when the crop cannot be made. Reads array shapes, and with
    check_blank the pixels under each trace at the first scale level."""
    groups = [src_group[f"scale_{scale}"] for scale in scales]
    names, match = matchImageNames(series, scales, groups, match_by_number)

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
    # a section whose image is all 0 under its trace shows nothing; it is
    # written like a missing image and never lends its window
    blank = []
    for snum in sorted(usable) if check_blank else ():
        if names[snum] not in groups[0]:
            continue
        image = groups[0][names[snum]]
        bounds, mag = traced[snum]
        window = usableWindow(bounds, radius, mag * scales[0], image.shape)
        if window is not None and blankUnder(image, window):
            blank.append(snum)
    if blank and not set(usable) - set(blank):
        raise CropError(
            f"The crop would be empty: the image under {obj_name!r} is all 0 on every "
            f"section with it ({spans(blank, 4)}). Use --keep-blank-images to crop it anyway."
        )
    whole = [snum for snum in sorted(usable) if snum not in missing and snum not in blank]
    neighbor = {
        snum: min(whole, key=lambda k: (abs(k - snum), k)) if whole else None
        for snum in snums
        if snum not in traced or snum in missing or snum in blank
    }
    # blank sections become gray only when gray stand-ins are on
    grayed = [snum for snum in blank if gray_missing and neighbor[snum] is not None]

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

    # a stand-in takes its neighbor's image type, which must have a mid-gray
    grays = set()
    stand_ins = {snum: absent for snum, absent in missing.items() if gray_missing}
    stand_ins.update({snum: scales for snum in grayed})
    for snum, absent in sorted(stand_ins.items()):
        nearest = neighbor[snum]
        if nearest is None:
            continue
        for scale, group in zip(scales, groups):
            if scale not in absent:
                continue
            dtype = group[names[nearest]].dtype
            if midGray(dtype) is None:
                problem = ("has no image in the zarr" if snum in missing
                           else f"has an image that is all 0 under {obj_name}")
                fix = ("--skip-missing to leave it out" if snum in missing
                       else "--keep-blank-images to crop it as it is")
                raise CropError(
                    f"Section {snum} {problem}, and a stand-in would be "
                    f"{dtype} like the zarr's images, which has no fixed mid-gray. "
                    f"Use {fix}."
                )
            grays.add(midGray(dtype))
    return CropPlan(
        names=names, match=match, traced=traced, missing=missing,
        untraced=untraced, neighbor=neighbor, windows=windows, failed=failed,
        fill=fill_untraced, gray=gray_missing, full=full_on_fail, grays=sorted(grays),
        blank=blank, grayed=grayed,
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
    cropped = [
        snum for snum in plan.traced
        if snum not in plan.missing and snum not in plan.failed and snum not in plan.grayed
    ]
    summary = [f"Cropped around {obj_name}: {len(cropped)} of {plural(len(sections), 'section')}."]
    details = []

    if plan.match:
        first = min(sections)
        summary.append(
            f"Image names: no series name is in the zarr, so each section uses the zarr "
            f"image with the same number as its own image ({plan.names[first]!r} for "
            f"{sections[first]['src']!r}), by the {plan.match['zarr']} number in the zarr's "
            f"names and the {plan.match['series']} in the series'. The crop uses the series' names."
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

    if plan.blank:
        head = (f"Image all 0 under {obj_name} on {plural(len(plan.blank), 'section')} "
                f"({spans(plan.blank)})")
        if not plan.gray:
            summary.append(f"{head}: cropped as it is (--skip-missing).")
        elif not plan.grayed:
            summary.append(f"{head}: cropped as it is, because {no_reference}.")
        else:
            summary.append(
                f"{head}: mid-gray ({', '.join(str(gray) for gray in plan.grays)}) inside the "
                f"window of the nearest other section with {obj_name}, at that section's image size."
            )
            details += ["", f"Sections whose image is all 0 under {obj_name} "
                            "(section, series image name: the section whose window and size it used)"]
            details += [f"  {snum} {sections[snum]['src']}: {plan.neighbor[snum]}" for snum in plan.grayed]

    if plan.missing:
        head = f"No image in the zarr for {plural(len(plan.missing), 'section')} ({spans(plan.missing)})"
        if not plan.gray:
            summary.append(f"{head}: left out of the crop (--skip-missing).")
        elif plan.neighbor[min(plan.missing)] is None:
            summary.append(f"{head}: left out of the crop, because {no_reference}.")
        else:
            summary.append(
                f"{head}: mid-gray ({', '.join(str(gray) for gray in plan.grays)}) inside the "
                f"window of {nearest}, at that section's image size."
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
        check_blank : bool = True,
        jser_fp : str = "",
        tool : str = "",
        echo=print,
        progress=None,
        should_stop=None):
    """Write the cropped images for every section, and the log, into new_zarr_fp.

        Params:
            report (bool): print progress lines to stdout for a wrapper program
            fill_untraced, gray_missing, match_by_number, full_on_fail,
                check_blank (bool): see planCrop
            jser_fp (str): the series file named in the log
            tool (str): what made the crop, for the log's Tool line; this
                PyReconstruct (appTool) when blank
            echo (callable): takes each line of the summary and the log's
                path, as the crop finishes; print by default
            progress (callable): takes the percent done, after each section
            should_stop (callable): asked before each section; True stops
                the crop with CropStopped, before that section is written
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
                    fill_untraced, gray_missing, match_by_number, full_on_fail, check_blank)
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
        if should_stop is not None and should_stop():
            raise CropStopped(done - 1, total, new_zarr_fp)
        name = plan.names[snum]
        nearest = plan.neighbor.get(snum)

        # crop the image at every scale level; the output keeps the series' name
        for scale in scales:
            scale_grp = f"scale_{scale}"
            group = src_group[scale_grp]
            if name in group and snum not in plan.grayed:
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
                    gray[t:b, l:r] = midGray(like.dtype)
                writeImage(new_group, scale_grp, section.src, gray, like)

        if report:
            print(f"Cropped section {snum}", flush=True)
            print(f"@@PROGRESS@@ STEP {done} {total}", flush=True)
        if progress is not None:
            progress(done / total * 100)

    # written last, so a log in the output means the crop finished
    about = [("Tool", tool or appTool()),
             ("Series", jser_fp or series.jser_fp),
             ("Source zarr", getattr(src_group.store, "path", "")),
             ("Output zarr", new_zarr_fp)]
    summary, text = describeCrop(plan, series, obj_name, radius, scales, about)
    log_fp = os.path.join(new_zarr_fp, LOG_NAME)
    with open(log_fp, "w", encoding="utf-8", errors=EXPORT_ERRORS) as log:
        log.write(text)
    for line in summary:
        echo(line)
    echo(f"Log: {log_fp}")
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
        full_on_fail : bool = True,
        check_blank : bool = True,
        tool : str = ""):
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
            fill_untraced, gray_missing, match_by_number, full_on_fail,
                check_blank (bool): see the module docstring; each is on
                unless turned off
            tool (str): the log's Tool line (see cropSections)
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
            check_blank=check_blank,
            jser_fp=os.path.realpath(series_fp), tool=tool,
        )
    finally:
        series.close()
    return out_fp



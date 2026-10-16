"""Crop a series' zarr images down to one object.

Every image keeps its size. Pixels outside the object's bounds, plus a radius
in microns, are set to zero, at every scale_N level.

Run with no arguments to be asked for each value. Run with flags to skip the
questions, for example from another program:

    python crop_zarr.py --jser series.jser --object dendrite_1 --radius 2
        [--zarr images.zarr] [--out cropped.zarr]

With flags, progress goes to stdout as the same "@@PROGRESS@@" lines the zarr
converter prints, and errors exit nonzero before anything is written.

Five gaps in the data are handled, each on by default with a flag to turn
it off:
- A section without the object keeps its image inside the window of the
  nearest section with the object (ties go to the earlier section), instead
  of coming out black. --blank-untraced leaves it black.
- A section whose image is not in the zarr gets an image the size of the
  nearest section with the object, mid-gray inside that section's window and
  0 outside it, so the crop has an image for every section. Mid-gray is half
  the range of an unsigned image type: 128 for 8-bit images, 32768 for
  16-bit. Signed, float and bool images have no fixed black and white, so a
  missing image there stops the crop before it writes anything.
  --skip-missing writes no image for it instead.
- A section with the object whose image is all 0 under it at the first scale
  level (the zarr stored no data there) is written like a missing image:
  mid-gray in the nearest other section's window. It never lends its window
  to other sections. --keep-blank-images crops it as it is.
- When no image name in the series is in the zarr, each section is matched
  to the zarr image with the same number as the section's own image name,
  taking the first or the last number in the names (matchByNumber). Only
  an exact match is used: one image per section, no number twice, the same
  names at every scale level, and every image name numbered as its section
  (a reordered series is refused). The crop names its images as the series
  does. --exact-names turns the matching off.
- A section that has an image but where no window keeps any of its pixels
  keeps its full, uncropped image instead of coming out black. That is when
  the object's window is outside the image, the borrowed window of the
  nearest section is outside this image, the mag or trace is not a usable
  number, or there is no section to borrow a window from. --blank-failed
  leaves it black. A crop where no section with the object keeps pixels is
  still an error, below.

Every run writes crop_log.txt inside the output zarr: which copy of the
script made it, the inputs, a summary, and each section that was filled,
made gray, kept whole or matched by number. The summary is printed too, and
the copy of the script is printed first of all, so a run from an old install
shows itself before it does any work.

The crop itself is PyReconstruct/modules/backend/crop_zarr.py, which the
dialog under Series > Images in PyReconstruct runs too; this script is the
command line in front of it.

A crop that would keep no pixels is an error too, found before the output
folder is made: when no section's image name is in the zarr and the names
cannot be matched by number (the series and the zarr do not belong
together), or when the object is inside no section image.

The output must be a new path: not one that exists, not a drive or file
system root, and not the source zarr, inside it, or a folder that holds it.
Neither path may have a "." or ".." part after a folder name; "./" and "../"
at the start are fine.
The script never deletes anything; remove an old output yourself to reuse
its name. That includes the partial output a stopped run leaves behind.
"""

import argparse
import functools
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

# add src modules to the system path
sys.path.append(os.path.join(os.getcwd(), "..", ".."))
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.progress import NullProgressReporter
# the crop, under this script's names: a wrapper program that imports this
# file reaches every step here, as before
from PyReconstruct.modules.backend.crop_zarr import (  # noqa: F401
    LOG_NAME, CropError, CropPlan, CropStopped,
    blankUnder, checkObject, checkPixelsKept, checkPlainPath, cropSections,
    cropZarr, defaultOutput, describeCrop, isRoot, isWithin, matchImageNames,
    midGray, openSource, outputExists, pixelWindow, planCrop, resolvePaths,
    sameNamesAtEveryScale, trimSeparators, usableWindow, writeImage,
)
from PyReconstruct.modules.backend.image_name_match import (  # noqa: F401
    matchByNumber, nameNumbers, numberKeys, plural, someNames, spans,
)


@functools.cache
def toolVersion():
    """Which copy of this script is running, for the screen and the log.

    A SOURCE file beside the script names the fork commit it was installed
    from ("dustenhubbard/pyreconstruct <commit> <subject>", as an installer
    writes it). Without one, the script is run from a checkout and
    git names its commit, with "(modified)" when the file differs from it
    and "(modified or not: unknown)" when git could not say.
    "unknown source" when neither answers, so the log always has the line.
    Worked out once per run, so the screen and the log cannot disagree."""
    script = os.path.abspath(__file__)
    here = os.path.dirname(script)
    try:
        with open(os.path.join(here, "SOURCE"), encoding="utf-8") as source:
            words = source.readline().split()
        if len(words) >= 2 and re.fullmatch(r"[0-9a-f]{7,40}", words[1]):
            return f"{words[0]} {words[1][:12]}"
    except (OSError, UnicodeDecodeError):
        pass
    try:
        git = ["git", "-C", here]
        head = subprocess.run(
            git + ["rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        commit = head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown source"
    if head.returncode != 0 or not commit:
        return "unknown source"
    # a status that failed, or never answered, says nothing about the file:
    # keep the commit git did name, and never call the file clean on no evidence
    try:
        status = subprocess.run(
            git + ["status", "--porcelain", "--", script],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return f"checkout {commit} (modified or not: unknown)"
    if status.returncode != 0:
        return f"checkout {commit} (modified or not: unknown)"
    return f"checkout {commit}" + (" (modified)" if status.stdout.strip() else "")



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
                        "instead of mid-gray in the nearest traced section's window")
    parser.add_argument("--exact-names", action="store_true",
                        help="when no image name in the series is in the zarr, stop, instead "
                        "of matching images by the number in their names")
    parser.add_argument("--blank-failed", action="store_true",
                        help="leave a section black when no window keeps any of its pixels, "
                        "instead of keeping its full, uncropped image")
    parser.add_argument("--keep-blank-images", action="store_true",
                        help="crop a section whose image is all 0 under the object as it is, "
                        "instead of a mid-gray stand-in like a missing image")
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
            check_blank=not args.keep_blank_images,
            jser_fp=os.path.realpath(args.jser),
            tool=f"crop_zarr.py from {toolVersion()}",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Crop complete: {out_fp}", flush=True)
    return out_fp


def main(argv : list):
    # first of all, so an old install shows itself before it does any work
    print(f"crop_zarr.py from {toolVersion()}", flush=True)
    if not argv:
        jser_fp = input("Jser filepath: ")
        obj_name = input("Object name to crop around: ")
        radius = float(input("Radius around BOUNDARY of object to include: "))
        src_dir = input("Zarr location (leave blank to use the location stored in the series): ").strip()

        try:
            cropZarr(jser_fp, obj_name, radius, src_dir,
                     tool=f"crop_zarr.py from {toolVersion()}")
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

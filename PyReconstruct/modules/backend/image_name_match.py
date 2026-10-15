"""Pair a series' sections with the images of a zarr named another way.

A zarr made for a series may name its images differently from the series:
IMG_000.tif in the series, 000_IMG_grid000.tif in the zarr. Nothing then
loads, and the series' own names are the only clue. The rules here key each
side by the number in its names and pair the sections with the zarr's images
by that number. The same rules serve the cropper (dev/assets/misc/crop_zarr.py)
and the image folder change in the main window, so a match one of them makes
the other makes too.

Kept free of Qt and of the data model, so the cropper can import it without
a display and the rules can be checked on plain names.
"""
import os
import re


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


def nameNumbers(name : str):
    """Every run of digits in an image name, as integers, left to right.

    A file extension is left out (".jp2" is not a number), but only one with
    a letter in it, so the "000" of "CODE.000" stays.
    """
    stem, extension = os.path.splitext(name)
    if not re.search(r"[A-Za-z]", extension):
        stem = name
    return [int(run) for run in re.findall(r"[0-9]+", stem)]


def numberKeys(names : list):
    """The ways a list of image names can be keyed by one number per name.

    The first number in each name is a key when every name has one and no two
    are the same integer; so is the last. Zero padding does not count:
    "001_a.tif" and "1_b.tif" share the number 1.

        Returns:
            (tuple): ({"first" and/or "last": {number: name}}, "") or ({}, the
                reason neither is a key)
    """
    keys, reason = {}, ""
    for position, index in (("first", 0), ("last", -1)):
        key = {}
        for name in names:
            numbers = nameNumbers(name)
            if not numbers:
                return {}, f"{name!r} has no number"
            if numbers[index] in key:
                reason = reason or (
                    f"{key[numbers[index]]!r} and {name!r} both have the number {numbers[index]}"
                )
                break
            key[numbers[index]] = name
        else:
            keys[position] = key
    return keys, "" if keys else reason


def matchByNumber(series_names : dict, zarr_names : list):
    """Pair each section with the zarr image that has its image name's number.

    A pure function of the names. The key is the number in the series' own
    image name, which is the image the traces were drawn over, not the
    section number: after sections are inserted, removed or reordered the two
    differ. Each side is keyed by its first or last number (numberKeys). The
    number sets must be equal, so an offset, a missing image or an extra one
    is refused. When the first and the last number both fit and pair the
    images differently, the match is ambiguous and refused. When they give the
    same pairing, the reading with the fewest sections numbered unlike their
    image is returned.

        Params:
            series_names (dict): section number: the series' image name
            zarr_names (list): the zarr's image names
        Returns:
            (tuple): (match, "") or (None, the reason there is no match), where
                match is a dict with "names" (section number: zarr image name),
                "series" and "zarr" (the position, "first" or "last", of the
                number used in each side's names), and "renumbered" (the
                sections whose image name's number is not their section number)
    """
    if not zarr_names:
        return None, "the zarr holds no images"
    if not series_names:
        return None, "the series has no sections"
    zarr_keys, reason = numberKeys(zarr_names)
    if not zarr_keys:
        return None, f"no number tells the zarr's images apart: {reason}"
    series_keys, reason = numberKeys(list(series_names.values()))
    if not series_keys:
        return None, f"no number tells the series' image names apart: {reason}"

    section_of = {name: snum for snum, name in series_names.items()}
    pairings = {}
    for series_position, series_key in series_keys.items():
        for zarr_position, zarr_key in zarr_keys.items():
            if set(series_key) == set(zarr_key):
                names = {section_of[name]: zarr_key[number] for number, name in series_key.items()}
                # every reading that gives this pairing is kept, so the
                # section-number check below can use the one that fits
                pairings.setdefault(tuple(sorted(names.items())), []).append(
                    (series_position, zarr_position, names))
    if not pairings:
        zarr_key = next(iter(zarr_keys.values()))
        series_key = next(iter(series_keys.values()))
        return None, (
            f"the zarr's {plural(len(zarr_key), 'image')} are numbered "
            f"{spans(zarr_key, 4) or 'nothing'}, and the series' "
            f"{plural(len(series_key), 'image name')} {spans(series_key, 4)}"
        )
    if len(pairings) > 1:
        return None, (
            "the first and the last number in the names both fit and pair the images "
            "differently, so which one is meant is not clear"
        )
    (readings,) = pairings.values()
    matches = []
    for series_position, zarr_position, names in readings:
        renumbered = sorted(
            section_of[name] for number, name in series_keys[series_position].items()
            if section_of[name] != number
        )
        matches.append({"names": names, "series": series_position, "zarr": zarr_position,
                        "renumbered": renumbered})
    # the same pairing read another way may number every section as its own
    return min(matches, key=lambda match: len(match["renumbered"])), ""


def zarrImageNames(zarr_dir : str):
    """The image names a zarr holds where PyReconstruct reads them, sorted.

    A zarr with scale levels keeps its full-resolution images under scale_1;
    one in the flat layout keeps each image at the root, with no scale level
    (the rule Section.zarr_flat applies: a scale_N entry that is itself an
    image array is not a scale level). An entry is an image when it holds a
    .zarray. A nested name (a/b.png) is not listed, the same as the cropper's
    reading of a scale group. Raises OSError when the folder cannot be listed.

        Params:
            zarr_dir (str): the zarr folder
        Returns:
            (list): the image names, sorted
    """
    entries = os.listdir(zarr_dir)
    if any(_isScaleLevel(zarr_dir, name) for name in entries):
        folder = os.path.join(zarr_dir, "scale_1")
        if not os.path.isdir(folder):
            return []
        entries = os.listdir(folder)
    else:
        folder = zarr_dir
    return sorted(
        name for name in entries
        if os.path.isfile(os.path.join(folder, name, ".zarray"))
    )


def _isScaleLevel(zarr_dir : str, name : str) -> bool:
    """Whether a zarr root entry is a scale level rather than an image."""
    return (
        name.startswith("scale_") and
        name.split("_")[1].isnumeric() and
        not os.path.isfile(os.path.join(zarr_dir, name, ".zarray"))
    )

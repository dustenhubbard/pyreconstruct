#!/usr/bin/env python
# -*- mode: python -*-

import re
import sys
import copy
import json
import locale
from pathlib import Path
from datetime import datetime as dt
from typing import Union


class DerandomizeError(Exception):
    """Raised when a project cannot be decoded.

    Raised before any file is moved, or after a failed move has been rolled
    back, unless the message lists what could not be put back.
    """


def split_image_path(image: str) -> tuple:
    """Split a decode.txt image path into (series, image name).

    randomize.py writes the path relative to the project folder with "/", but
    a decode.txt written on Windows by an older version uses "\\". Both
    separators are accepted so a decode.txt from any platform decodes.
    """

    parts = [p for p in re.split(r"[\\/]", image) if p]

    if len(parts) != 2:
        raise DerandomizeError(
            f"'{image}' in decode.txt is not in the form series/image."
        )

    return tuple(parts)


def get_decoding(project_dir):
    """Get decoding information as a dictionary.

    "images" maps each coded image name to its (series, image name).
    """

    images = {}

    ## randomize.py writes UTF-8; an older version used the locale encoding
    raw = (project_dir / "decode.txt").read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode(locale.getpreferredencoding(False))
        except UnicodeDecodeError:
            raise DerandomizeError("decode.txt is not readable text.")

    for line in text.splitlines():

        if not line.strip():
            continue

        if " -> " not in line:
            raise DerandomizeError(
                f"'{line}' in decode.txt is not in the form "
                "series/image -> coded image."
            )

        image, coded = line.strip().rsplit(" -> ", 1)
        images[coded] = split_image_path(image)

    decoding = {
        "series" : sorted(set(series for series, _ in images.values())),
        "images" : images
    }

    return decoding


def _listing(problem: str, items: list) -> str:
    """Describe a problem and the first few items it applies to."""

    shown = ", ".join(str(i) for i in items[:5])
    more = f" and {len(items) - 5} more" if len(items) > 5 else ""

    return f"{problem}: {shown}{more}"


def _decoded_series_data(data, decoding, series):
    """Build the jser data for one decoded series without touching any file.

    Sections keep their order by original image name and are renumbered from
    0, and z-trace points follow their sections to the new numbers. Points on
    another series' sections are dropped, and a z-trace left with no points is
    dropped with its attributes and group memberships.
    """

    rows = []

    for snum, section in enumerate(data["sections"]):

        if section is None:  # deleted section
            continue

        img_series, img_name = decoding["images"][section["src"]]

        if img_series == series:
            rows.append((img_name, snum, section))

    rows.sort(key=lambda row: row[0])
    new_snums = {old: new for new, (_, old, _) in enumerate(rows)}

    series_data = copy.deepcopy(data["series"])

    ztraces = {}

    for name, ztrace in series_data.get("ztraces", {}).items():

        points = [
            [x, y, new_snums[snum]]
            for x, y, snum in ztrace["points"]
            if snum in new_snums
        ]

        if points:
            ztraces[name] = dict(ztrace, points=points)

    for name in set(series_data.get("ztraces", {})) - set(ztraces):
        series_data.get("ztrace_attrs", {}).pop(name, None)

    for group, members in series_data.get("ztrace_groups", {}).items():
        series_data["ztrace_groups"][group] = [m for m in members if m in ztraces]

    series_data["ztraces"] = ztraces

    return {
        **data,
        "sections": [dict(section, src=name) for name, _, section in rows],
        "series": series_data,
    }


def _write_decoded(project_dir, images_dir, save_coding_dir, coded,
                   decoding, decoded, done):
    """Write the decoded series and move every file, recording each step.

    `done` gets one entry per finished step, so a failed step can be undone.
    """

    ## Create the decoded series
    for series, series_data in decoded.items():

        for d in (project_dir / series, project_dir / series / "images"):
            if not d.exists():
                d.mkdir()
                done.append(("mkdir", d))

        series_jser = project_dir / series / f"{series}.jser"
        done.append(("write", series_jser))
        with series_jser.open("w", encoding="utf-8") as fp:
            fp.write(json.dumps(series_data))

    def move(src, dst):
        src.rename(dst)
        done.append(("move", src, dst))

    ## Move images, including any that no longer have a section
    for coded_name, (series, name) in decoding["images"].items():
        move(images_dir / coded_name, project_dir / series / "images" / name)

    ## Move the coded files aside, with anything left in images/
    save_coding_dir.mkdir()
    done.append(("mkdir", save_coding_dir))

    if any(images_dir.iterdir()):
        move(images_dir, save_coding_dir / "images")
    else:
        images_dir.rmdir()
        done.append(("rmdir", images_dir))

    move(coded, save_coding_dir / coded.name)
    move(project_dir / "decode.txt", save_coding_dir / "decode.txt")


def _roll_back(done) -> list:
    """Undo recorded steps, newest first. Returns what could not be undone."""

    stuck = []

    for step in reversed(done):
        try:
            if step[0] == "move":
                step[2].rename(step[1])
            elif step[0] == "write":
                step[1].unlink(missing_ok=True)
            elif step[0] == "mkdir":
                step[1].rmdir()
            elif step[0] == "rmdir":
                step[1].mkdir()
        except OSError:
            stuck.append(step[-1])

    return stuck


def derandomize_project(coded_series_fp: Union[str, Path]) -> Path:
    """Derandomize a project.

    Everything is checked before any file is moved, so a project that cannot
    be decoded is left exactly as it was and a DerandomizeError says why.
    """

    coded = Path(coded_series_fp)
    project_dir = coded.parent
    images_dir = project_dir / "images"
    save_coding_dir = project_dir / f"decoded-{dt.now().strftime('%y%m%d')}"

    ## Get decoding information
    decoding = get_decoding(project_dir)

    with coded.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    ## Check everything before changing anything
    problems = []

    unknown = [
        section["src"] for section in data["sections"]
        if section is not None and section["src"] not in decoding["images"]
    ]
    if unknown:
        problems.append(_listing("Images not listed in decode.txt", unknown))

    missing = [
        coded_name for coded_name in decoding["images"]
        if not (images_dir / coded_name).is_file()
    ]
    if missing:
        problems.append(_listing(f"Images missing from {images_dir}", missing))

    targets = [
        project_dir / series / "images" / name
        for series, name in decoding["images"].values()
    ]
    targets += [
        project_dir / series / f"{series}.jser" for series in decoding["series"]
    ]
    targets.append(save_coding_dir)

    existing = [t for t in targets if t.exists()]
    if existing:
        problems.append(_listing("These already exist", existing))

    ## two targets that differ only in case are one file on macOS and Windows
    seen = {}
    repeated = []
    for t in targets:
        key = str(t).casefold()
        if key in seen:
            repeated.append(f"{seen[key]} and {t}")
        else:
            seen[key] = t
    if repeated:
        problems.append(_listing("These would be the same file", repeated))

    if problems:
        raise DerandomizeError(
            "Nothing was changed.\n\n" + "\n\n".join(problems)
        )

    date = dt.now().strftime("%y-%m-%d")
    time = dt.now().strftime("%H:%M")
    log_info = f"\n{date}, {time}, computer, -, -, Decoded series"

    decoded = {}

    for series in decoding["series"]:

        series_data = _decoded_series_data(data, decoding, series)

        series_img_dir = project_dir / series / "images"

        series_data["series"]["code"] = series
        series_data["series"]["current_section"] = 0
        series_data["series"]["src_dir"] = str(series_img_dir)
        series_data["log"] = data["log"] + log_info

        decoded[series] = series_data

    done = []

    try:
        _write_decoded(project_dir, images_dir, save_coding_dir, coded,
                       decoding, decoded, done)
    except OSError as e:
        stuck = _roll_back(done)
        if stuck:
            raise DerandomizeError(
                f"Decoding stopped: {e}\n\n"
                + _listing("These could not be put back", stuck)
            ) from e
        raise DerandomizeError(
            f"Decoding stopped and every change was undone: {e}"
        ) from e

    return project_dir


if __name__ == '__main__':

    args = sys.argv

    if not len(args) == 2 or not args[1].endswith(".jser"):
        print("Provide a single coded jser as an argument.")
        sys.exit(1)

    project_dir = Path(args[1])

    derandomize_project(project_dir)

    print("Project decoded.")

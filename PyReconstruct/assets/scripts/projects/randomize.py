#!/usr/bin/env python
# -*- mode: python -*-

import sys
import uuid
from pathlib import Path
from typing import Union

from PyReconstruct.modules.datatypes import Series


IMAGE_SUFFIXES = {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".bmp"}


class RandomizeError(Exception):
    """Raised before any file is moved when a project cannot be randomized."""


def is_image(fp: Path) -> bool:
    """Return True for a visible image file with a supported extension.

    Extensions match in any case (`.TIF` as well as `.tif`), and hidden files
    such as `.DS_Store` are never treated as images.
    """

    return (
        fp.is_file()
        and not fp.name.startswith(".")
        and fp.suffix.lower() in IMAGE_SUFFIXES
    )


def find_images(project_dir: Path) -> list:
    """Return the images in each series subfolder of a project."""

    images = []

    for series in sorted(project_dir.iterdir()):

        if (
            series.name == "images"
            or series.name.startswith(".")
            or not series.is_dir()
        ):
            continue

        images.extend(sorted(p for p in series.iterdir() if is_image(p)))

    return images


def randomize_images(project_dir, images):
    """Randomize and collect images."""

    decode_file = project_dir / "decode.txt"
    series_dirs = []

    with decode_file.open("w") as text:

        for image in images:

            ## Generate coded name
            new_name = f"{str(uuid.uuid4())}.{image.suffix[1:]}"

            ## Write decoding info (always with "/" so any platform can read it)
            text.write(
                f"{image.relative_to(project_dir).as_posix()} -> {new_name}\n"
            )

            ## Rename and move image
            image.rename(project_dir / "images" / new_name)

            if image.parent not in series_dirs:
                series_dirs.append(image.parent)

    ## Remove directories left empty (other files stay where they are)
    for series in series_dirs:
        if not any(series.iterdir()):
            series.rmdir()


def sort_images(image_dir):
    """Sort images by name."""

    images = [fp for fp in image_dir.iterdir() if is_image(fp)]

    images_sorted = [
        str(elem)
        for elem
        in sorted(
            images, key=lambda p: p.name
        )
    ]

    return images_sorted


def create_new(img_dir):
    """Create a new series."""

    images_list = sort_images(img_dir)
    mag = 0.00254
    th = 0.05

    with Series.new(images_list, "coded", mag, th) as series:

        fp = img_dir / "../coded.jser"
        series.saveJser(str(fp))

    return fp.resolve()


def main(project_dir: Union[str, Path]) -> Path:
    """Main."""

    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)
    
    new_img_dir = project_dir / "images"

    if new_img_dir.exists() or (project_dir / "decode.txt").exists():
        raise RandomizeError(
            f"{project_dir} already has an images folder or a decode.txt. "
            "It looks like it was randomized before, so nothing was changed."
        )

    images = find_images(project_dir)

    if not images:
        raise RandomizeError(
            f"No images were found in the subfolders of {project_dir}, "
            "so nothing was changed."
        )

    new_img_dir.mkdir()

    randomize_images(project_dir, images)

    return create_new(new_img_dir)


if __name__ == '__main__':

    args = sys.argv

    if not len(args) == 2:
        print("Provide a single directory as an argument.")
        sys.exit(1)
        
    project_dir = Path(args[1])

    fp = main(project_dir)

    print(f"Jser ready in {fp}")

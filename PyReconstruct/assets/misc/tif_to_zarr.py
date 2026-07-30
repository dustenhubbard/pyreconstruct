"""Convert a folder of images into a flat zarr store, interactively.

Superseded in the app by ``Series > Images > Convert to scaled images``, which
writes the multiscale ``scale_N`` layout that ``ImageLayer.loadImage`` prefers.
This script writes one zarr array per image at the top level of the store, the
pre-scale layout; the app still accepts it, but only by migrating the store into
``scale_1/`` in place on first open.

Kept as a standalone fallback for a checkout. Run it from the repository root::

    uv run python PyReconstruct/assets/misc/tif_to_zarr.py

It prompts for the image folder and the store name, so it needs a terminal and a
display. Two wrapper scripts used to sit beside it, ``tif_to_zarr.sh`` and
``tif_to_zarr.bat``; both invoked ``src/assets/misc/tif_to_zarr.py`` and sourced
an ``env/`` virtualenv, neither of which has existed since the 2023 move to a
pip-installable layout, so they were removed rather than rewritten.
"""

import os
import cv2
import zarr

from PySide6.QtWidgets import QApplication, QFileDialog

input("Press enter to locate the images folder.")
app = QApplication([])
img_dir = QFileDialog.getExistingDirectory(
    caption="Locate Images Folder"
)
if not img_dir:
    exit()

os.chdir(img_dir)

zarr_name = input("\nWhat would you like to name your zarr file?: ")
if not zarr_name.endswith(".zarr"):
    zarr_name = zarr_name + ".zarr"

for fname in os.listdir("."):
    print(f"Working on {fname}...")
    try:
        cvim = cv2.imread(fname, cv2.IMREAD_GRAYSCALE)
        zarr.save(os.path.join(zarr_name, fname), cvim)
    except:
        print("File is not an image.")

print()
print("Images successfully exported as zarr directory to:")
print(f"{img_dir}/{zarr_name}")
print()
print("Open series, then SERIES > FIND IMAGES and point to this zarr directory.")
print()
print("Happy scrolling!")

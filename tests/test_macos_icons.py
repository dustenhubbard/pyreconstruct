"""The macOS .icns files: complete, in step with the PNG icons, and used by the
app bundle and the installer image."""

import io
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "packaging" / "macos"
IMG = ROOT / "PyReconstruct" / "assets" / "img"

# Every slot macOS reads, with its pixel size.
SLOTS = {"icp4": 16, "icp5": 32, "ic11": 32, "ic12": 64, "ic07": 128,
         "ic13": 256, "ic08": 256, "ic14": 512, "ic09": 512, "ic10": 1024}
FLAVORS = [("stable", "PyReconstruct.icns", "PyReconstruct.png"),
           ("dev", "PyReconstructDev.icns", "PyReconstructDev.png")]


def read_icns(path):
    data = path.read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    chunks, at = {}, 8
    while at < len(data):
        code, size = data[at:at + 4].decode("ascii"), struct.unpack(">I", data[at + 4:at + 8])[0]
        assert size > 8 and at + size <= len(data)
        chunks[code] = data[at + 8:at + size]
        at += size
    return chunks


@pytest.mark.parametrize("flavor,icns,png", FLAVORS)
def test_icns_holds_every_size_as_png(flavor, icns, png):
    chunks = read_icns(MACOS / icns)
    assert set(chunks) == set(SLOTS)
    for code, px in SLOTS.items():
        im = Image.open(io.BytesIO(chunks[code]))
        assert im.format == "PNG" and im.size == (px, px), code


@pytest.mark.parametrize("flavor,icns,png", FLAVORS)
def test_icns_matches_the_png_icon(flavor, icns, png):
    """The 1024 px slot is the same picture as the PNG the app and its guide use."""
    big = Image.open(io.BytesIO(read_icns(MACOS / icns)["ic10"])).convert("RGBA")
    assert big.tobytes() == Image.open(IMG / png).convert("RGBA").tobytes()


def test_the_two_flavors_differ():
    stable = read_icns(MACOS / "PyReconstruct.icns")
    dev = read_icns(MACOS / "PyReconstructDev.icns")
    assert all(stable[code] != dev[code] for code in SLOTS)


@pytest.mark.parametrize("flavor,icns,png", FLAVORS)
def test_make_icns_copies_the_flavors_icon(tmp_path, flavor, icns, png):
    shutil.copytree(MACOS, tmp_path / "packaging" / "macos")
    if flavor == "dev":
        (tmp_path / "packaging" / "FLAVOR").write_text("dev\n")
    subprocess.run(["bash", "packaging/macos/make_icns.sh"], cwd=tmp_path,
                   check=True, capture_output=True, text=True)
    assert (tmp_path / "packaging" / "PyReconstruct.icns").read_bytes() == (MACOS / icns).read_bytes()


def test_dmg_volume_takes_the_icon_it_is_given():
    defines = {"app": "dist/PyReconstruct.app", "background": str(MACOS / "dmg-background.png"),
               "icon": str(MACOS / "PyReconstruct.icns")}
    settings = {"defines": defines}
    exec(compile((MACOS / "dmg_settings.py").read_text(), "dmg_settings.py", "exec"), settings, settings)
    assert settings["icon"] == defines["icon"]

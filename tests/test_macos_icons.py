"""The macOS .icns files: complete, in step with the PNG icons, and used by the
app bundle and the installer image."""

import io
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "packaging" / "macos"
IMG = ROOT / "PyReconstruct" / "assets" / "img"

# Every slot iconutil writes, with its pixel size and its name in an .iconset.
SLOTS = {"ic04": (16, "icon_16x16"), "ic05": (32, "icon_32x32"),
         "ic11": (32, "icon_16x16@2x"), "ic12": (64, "icon_32x32@2x"),
         "ic07": (128, "icon_128x128"), "ic13": (256, "icon_128x128@2x"),
         "ic08": (256, "icon_256x256"), "ic14": (512, "icon_256x256@2x"),
         "ic09": (512, "icon_512x512"), "ic10": (1024, "icon_512x512@2x")}
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
    chunks.pop("info", None)
    return chunks


def unpack_bits(data, count):
    """The icns run-length coding: returns `count` bytes and how many were read."""
    out, at = bytearray(), 0
    while len(out) < count:
        n = data[at]
        if n < 128:
            out += data[at + 1:at + n + 2]
            at += n + 2
        else:
            out += data[at + 1:at + 2] * (n - 125)
            at += 2
    return bytes(out[:count]), at


def decode_slot(data, px):
    """A slot's picture as RGBA: a PNG, or the ARGB form iconutil uses for 16 and 32 px."""
    if data[:4] != b"ARGB":
        return Image.open(io.BytesIO(data)).convert("RGBA")
    rest, planes = data[4:], []
    for _ in range(4):
        plane, used = unpack_bits(rest, px * px)
        planes.append(Image.frombytes("L", (px, px), plane))
        rest = rest[used:]
    a, r, g, b = planes
    return Image.merge("RGBA", (r, g, b, a))


@pytest.mark.parametrize("flavor,icns,png", FLAVORS)
def test_icns_holds_every_size(flavor, icns, png):
    chunks = read_icns(MACOS / icns)
    assert set(chunks) == set(SLOTS)
    for code, (px, _) in SLOTS.items():
        assert decode_slot(chunks[code], px).size == (px, px), code


@pytest.mark.skipif(sys.platform != "darwin", reason="iconutil is macOS only")
@pytest.mark.parametrize("flavor,icns,png", FLAVORS)
def test_macos_reads_every_size_as_drawn(tmp_path, flavor, icns, png):
    """macOS decodes each slot to the picture stored in it. It reads PNG data in
    the 16 and 32 px slots (icp4, icp5) as noise, so those must be ARGB."""
    iconset = tmp_path / "out.iconset"
    subprocess.run(["iconutil", "-c", "iconset", str(MACOS / icns), "-o", str(iconset)],
                   check=True, capture_output=True)
    names = {**SLOTS, "icp4": SLOTS["ic04"], "icp5": SLOTS["ic05"]}
    for code, data in read_icns(MACOS / icns).items():
        px, name = names[code]
        stored = np.asarray(decode_slot(data, px).convert("RGBa"), float)
        shown = np.asarray(Image.open(iconset / f"{name}.png").convert("RGBa"), float)
        assert shown.shape == stored.shape, name
        assert np.array_equal(shown[..., 3], stored[..., 3]), name
        assert np.abs(shown - stored).mean() < 2, name


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

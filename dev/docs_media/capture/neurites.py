"""A made-up series of simple neural shapes, for the User Guide's videos.

    python dev/docs_media/capture/neurites.py <folder>

Writes neurites.jser and one image per section into <folder>. Nothing in it is
lab data: every shape is drawn here from a formula, and the images are drawn
from the same shapes, so each trace follows the outline it sits on.

The four objects stand for what PyReconstruct is mostly used to trace, named the
way the lab names them (d dendrite, sp spine, ax axon, ast astroglia):

  * d01, a dendrite: a tube that runs at a slant through the sections;
  * d01sp01, a spine on it: a thin neck and a round head (ball and stick);
  * ax01, an axon: a thin string with three swellings (beads on a string);
  * ast01, an astroglial process: a thin curved sheet beside the dendrite.

The output depends on nothing but this file, so a rerun gives the same series.
"""

import json
import math
import sys
from pathlib import Path

SECTIONS = 40
THICKNESS = 0.05  # microns
MAG = 0.0025  # microns per pixel
IMAGE_SIZE = (1600, 1200)  # pixels: 4 x 3 microns
SEED = 466
CODE = "neuro"

PALETTE = json.loads((Path(__file__).resolve().parents[2] / "assets" / "checker" / "files"
                      / "shapes1.jser").read_text())["series"]

COLORS = {"d01": [255, 170, 0], "d01sp01": [255, 0, 255], "ax01": [0, 190, 255], "ast01": [0, 200, 90]}


def circle(cx, cy, r, n=64, wobble=0.0, phase=0.0):
    return [(cx + r * (1 + wobble * math.sin(3 * t + phase)) * math.cos(t),
             cy + r * (1 + wobble * math.sin(3 * t + phase)) * math.sin(t))
            for t in (2 * math.pi * i / n for i in range(n))]


def ball_and_stick(x0, hx, hy, r, w, n=48):
    """One outline: a neck from x0 to a round head of radius r centered at (hx, hy).

    The neck is 2w wide and meets the head where its edges cross the circle.
    """
    a = math.asin(w / r)
    xc = hx - r * math.cos(a)
    points = [(x0, hy + w), (xc, hy + w)]
    # around the head the long way, from the neck's upper edge to its lower
    for i in range(n + 1):
        t = (math.pi - a) - (2 * math.pi - 2 * a) * i / n
        points.append((hx + r * math.cos(t), hy + r * math.sin(t)))
    points += [(xc, hy - w), (x0, hy - w)]
    return points[:-1] if points[-1] == points[0] else points


def dendrite(k):
    u = k / (SECTIONS - 1)
    return 1.45 + 0.45 * u, 1.65 - 0.15 * u, 0.42


def shapes(k):
    """{name: [polygon, ...]} for section k, polygons in microns."""
    out = {}
    dx, dy, dr = dendrite(k)
    out["d01"] = [circle(dx, dy, dr, wobble=0.03, phase=k * 0.15)]

    # the spine: a head, round in z, on a thin neck that leaves the dendrite
    # to the right. Where the neck shows, head and neck are one outline,
    # which starts just inside the dendrite's edge so the two meshes meet.
    head_mid, head_half = 20, 7
    if abs(k - head_mid) < head_half:
        s = math.sqrt(1 - ((k - head_mid) / head_half) ** 2)
        hx, hy, hr = dx + dr + 0.55, dy - 0.05, 0.27 * s
        if abs(k - head_mid) <= 1:
            out["d01sp01"] = [ball_and_stick(dx + math.sqrt(dr ** 2 - (hy - dy) ** 2) - 0.02, hx, hy, hr, 0.05)]
        else:
            out["d01sp01"] = [circle(hx, hy, hr, n=48)]

    # the axon: thin, with three swellings along its length
    u = k / (SECTIONS - 1)
    ax, ay = 3.1 - 0.4 * u, 0.6 + 0.3 * u
    r = 0.075 + sum(0.2 * math.exp(-((k - c) / 2.6) ** 2) for c in (6, 20, 33))
    out["ax01"] = [circle(ax, ay, r, n=48)]

    # the astroglial process: a thin band around the dendrite's upper left
    start = math.radians(95 + 20 * math.sin(k / 7))
    span = math.radians(110 + 25 * math.cos(k / 9))
    inner, outer = dr + 0.09, dr + 0.17 + 0.03 * math.sin(k / 5)
    n = 40
    arc = [start + span * i / n for i in range(n + 1)]
    band = [(dx + outer * math.cos(t), dy + outer * math.sin(t)) for t in arc]
    band += [(dx + inner * math.cos(t), dy + inner * math.sin(t)) for t in reversed(arc)]
    out["ast01"] = [band]
    return out


def draw_image(polygons, path, rng):
    """A gray EM-like image: pale cells with dark membranes on a mottled ground."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    w, h = IMAGE_SIZE

    def px(points):
        return [(x / MAG, h - y / MAG) for x, y in points]

    ground = rng.normal(118, 10, (h // 12, w // 12)).clip(0, 255).astype("uint8")
    image = Image.fromarray(ground).resize((w, h), Image.BICUBIC)
    fills = {"d01": 196, "d01sp01": 196, "ax01": 182, "ast01": 150}
    # the membrane is the rim of each object's whole outline, so a spine's
    # neck and head read as one cell, and the neck joins the dendrite open
    masks = {}
    for name in ("ast01", "d01", "d01sp01", "ax01"):
        mask = Image.new("L", (w, h), 0)
        for poly in polygons.get(name, []):
            ImageDraw.Draw(mask).polygon(px(poly), fill=255)
        masks[name] = mask
    if "d01sp01" in polygons:
        masks["d01"] = Image.fromarray(np.maximum(np.asarray(masks["d01"]), np.asarray(masks["d01sp01"])))
        del masks["d01sp01"]
    for name, mask in masks.items():
        image.paste(fills[name], mask=mask)
        rim = np.asarray(mask, dtype=np.int16) - np.asarray(mask.filter(ImageFilter.MinFilter(7)))
        image.paste(58, mask=Image.fromarray(rim.clip(0, 255).astype("uint8")))
    draw = ImageDraw.Draw(image)
    # vesicles in the axon's swellings
    for poly in polygons["ax01"]:
        xs, ys = zip(*poly)
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        r = (max(xs) - min(xs)) / 2
        for _ in range(int(140 * max(0.0, r - 0.12))):
            a, d = rng.uniform(0, 2 * math.pi), r * 0.75 * math.sqrt(rng.uniform())
            x, y = (cx + d * math.cos(a)) / MAG, h - (cy + d * math.sin(a)) / MAG
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=80, width=3)
    image = image.filter(ImageFilter.GaussianBlur(2.2))
    # a light grain only: fine noise is what makes a video file large
    pixels = np.asarray(image, dtype=np.float32) + rng.normal(0, 1.5, (h, w))
    Image.fromarray(pixels.clip(0, 255).astype("uint8")).save(path)


def trace_row(points, color):
    return [[round(x, 7) for x, _ in points], [round(y, 7) for _, y in points], color,
            True, False, False, ["transparent", "selected"], []]


def write_series(folder, images=True):
    """Write the series into `folder`; return the path of the .jser.

    `images` False writes the .jser alone, for a quick check of its contents.
    """
    import numpy as np

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    sections = []
    for k in range(SECTIONS):
        polygons = shapes(k)
        src = f"neurites_{k:02d}.tif"
        if images:
            draw_image(polygons, folder / src, rng)
        sections.append({
            "src": src, "brightness": 0, "contrast": 0, "mag": MAG, "align_locked": True,
            "tforms": {"default": [1, 0, 0, 0, 1, 0]}, "thickness": THICKNESS,
            "contours": {name: [trace_row(p, COLORS[name]) for p in polys]
                         for name, polys in sorted(polygons.items())},
            "flags": [], "calgrid": False,
        })
    w, h = IMAGE_SIZE
    series = {
        "code": CODE, "current_section": 20, "src_dir": "",
        "window": [0, 0, w * MAG, h * MAG],
        # the trace palette as the shapes1 test series has it
        "palette_traces": PALETTE["palette_traces"], "current_trace": PALETTE["current_trace"],
        "ztraces": {},
        "alignment": "default", "object_groups": {}, "object_3D_modes": {},
        "options": {"autosave": False},
    }
    path = folder / "neurites.jser"
    path.write_text(json.dumps({"sections": sections, "series": series}))
    return path


if __name__ == "__main__":
    print(write_series(sys.argv[1]))

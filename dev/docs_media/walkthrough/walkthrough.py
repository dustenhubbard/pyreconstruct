#!/usr/bin/env python3
"""Render a screenshot walkthrough video from a scene file.

The video is built from still screen captures. The pointer, click rings,
drags and camera moves are drawn on top, so the result looks like a screen
recording without being one. README.md beside this file describes the step
list, the scene format and the capture, render and review workflow.

Commands:
  render  SCENE -o OUT.mp4 [--width 1920]   write the MP4 (H.264, no audio)
  still   SCENE -t SECONDS -o OUT.png        write one frame
  sheet   SCENE -o OUT.jpg                   one frame per second, for review
  compare A.mp4 B.mp4                        per-frame difference of two videos
  mask    IN.png OUT.png --box X0 Y0 X1 Y1   paint opaque privacy boxes
  verify  SCENE OUT.mp4 [OUT2.mp4 ...]       write verification.json beside SCENE
  draft   STEPS.json [-o scene.json]         turn a short step list into a scene

Needs Python 3 with Pillow and NumPy, and ffmpeg/ffprobe on PATH.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# The look, in pixels of a 3840-wide output. Everything scales with the
# output width. Measured from a reference walkthrough at 4K.
STYLE = {
    "fps": 60,
    "cursor_size": 76,          # scene files may override
    "cursor_fill": (27, 30, 35),
    "cursor_outline": (255, 255, 255),
    "cursor_outline_width": 3.5,
    "shadow_offset": (1.6, 5.3),
    "shadow_blur": 2.7,
    "shadow_opacity": 0.14,
    "cursor_fade": 0.4,         # seconds for the final fade out
    "ring_color": (179, 110, 100),
    "ring_width": 4.0,
    "ring_start_radius": 18.0,
    "ring_end_radius": 97.0,
    "ring_duration": 0.45,      # seconds
    "ring_hold": 0.033,         # seconds at the start radius
    "ring_opacity": 0.5,
    "mask_color": (236, 236, 234),
    # key casting: a badge at the bottom center naming the keys held
    "key_font": "/System/Library/Fonts/SFNS.ttf",
    "key_font_size": 74,
    "key_fill": (27, 30, 35),
    "key_opacity": 0.86,
    "key_text": (255, 255, 255),
    "key_pad": (46, 26),
    "key_radius": 28,
    "key_margin": 110,          # from the bottom edge
    "key_fade": 0.15,           # seconds in and out
    "crf": 17,
    "preset": "medium",
}

# Arrow pointer, filled part, for cursor_size 76. Hotspot at (0, 0).
ARROW = [(2.96, 5.64), (56.5, 45.92), (31.73, 46.36), (47.98, 79.11), (38.21, 85.05),
         (21.89, 51.11), (4.29, 67.11)]


def smootherstep(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


def smoothstep(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def bezier(p0, c1, c2, p1, s):
    return tuple((1 - s) ** 3 * p0[i] + 3 * (1 - s) ** 2 * s * c1[i]
                 + 3 * (1 - s) * s * s * c2[i] + s ** 3 * p1[i] for i in range(2))


def path_progress(u, ramp):
    """Share of a path's length covered at time share `u` of a drag: constant
    speed between an equal speed-up and slow-down, each `ramp` of the time."""
    u = min(max(u, 0.0), 1.0)
    if ramp and u < ramp:
        return u * u / (2 * ramp * (1 - ramp))
    if ramp and u > 1 - ramp:
        return 1 - (1 - u) ** 2 / (2 * ramp * (1 - ramp))
    return (u - ramp / 2) / (1 - ramp)


def polyline_prefix(path, progress):
    """The points of `path` up to `progress` of its length, ending exactly there."""
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    remaining = sum(lengths) * progress
    points = [tuple(path[0])]
    for a, b, length in zip(path, path[1:], lengths):
        if not length:
            continue
        if remaining < length:
            points.append(tuple(a[i] + (b[i] - a[i]) * remaining / length for i in range(2)))
            return points
        points.append(tuple(b))
        remaining -= length
    return points


class Scene:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.data = json.loads(self.path.read_text())
        d = self.data
        self.style = dict(STYLE)
        self.style.update(d.get("style", {}))
        self.style["cursor_size"] = d.get("cursor_size", self.style["cursor_size"])
        self.size = tuple(d["size"])
        self.duration = float(d["duration"])
        self.fps = int(d.get("fps", self.style["fps"]))
        self.targets = d.get("targets", {})
        self.images = {k: Image.open(self.path.parent / v).convert("RGB")
                       for k, v in d["images"].items()}
        for k, im in self.images.items():
            if im.size != self.size:
                sys.exit(f"{k}: image is {im.size}, scene size is {self.size}")
        self.states = sorted(d["states"], key=lambda s: s["time"])
        self.camera = sorted(d["camera"], key=lambda c: c["time"])
        self.moves = sorted(d.get("moves", []), key=lambda m: m["start"])
        for m in self.moves:
            if "path" in m:
                m["path"] = self.drag_path(m["path"])
        self.clicks = sorted(d.get("clicks", []))
        self.cursor_start = self.point(d.get("cursor_start", [self.size[0] / 2, self.size[1] / 2]))
        self.cursor_fade_out = d.get("cursor_fade_out")
        self.cursor_fade_in = d.get("cursor_fade_in")
        self.keys = d.get("keys", [])

    def point(self, p):
        """A point is [x, y] or the name of an entry in "targets"."""
        if isinstance(p, str):
            t = self.targets[p]
            p = t["center"] if isinstance(t, dict) else t
        return (float(p[0]), float(p[1]))

    def drag_path(self, p):
        """A path is a list of points or the name of a target with "points"."""
        if isinstance(p, str):
            p = self.targets[p]["points"]
        points = [self.point(q) for q in p]
        if len(points) < 2 or all(q == points[0] for q in points):
            sys.exit("A drag path needs two or more points and some length.")
        return points

    # -- timeline -------------------------------------------------------
    def camera_at(self, t):
        cam = self.camera
        if t <= cam[0]["time"]:
            c = cam[0]
            return c["x"], c["y"], c["zoom"]
        for a, b in zip(cam, cam[1:]):
            if a["time"] <= t <= b["time"]:
                span = b["time"] - a["time"]
                p = smootherstep((t - a["time"]) / span) if span > 0 else 1.0
                return tuple(a[k] + (b[k] - a[k]) * p for k in ("x", "y", "zoom"))
        c = cam[-1]
        return c["x"], c["y"], c["zoom"]

    def cursor_at(self, t):
        pos = self.cursor_start
        for m in self.moves:
            to = m["path"][-1] if "path" in m else self.point(m["to"])
            if t >= m["end"]:
                pos = to
                continue
            if t <= m["start"]:
                break
            if "path" in m:
                return polyline_prefix(m["path"], self.drag_progress(m, t))[-1]
            c = m.get("controls")
            if c:
                c1, c2 = self.point(c[0]), self.point(c[1])
            else:
                c1 = tuple(pos[i] + (to[i] - pos[i]) / 3 for i in range(2))
                c2 = tuple(pos[i] + (to[i] - pos[i]) * 2 / 3 for i in range(2))
            s = smootherstep((t - m["start"]) / (m["end"] - m["start"]))
            return bezier(pos, c1, c2, to, s)
        return pos

    @staticmethod
    def drag_progress(m, t):
        return path_progress((t - m["start"]) / (m["end"] - m["start"]), m.get("ease", 0.1))

    def strokes_at(self, t):
        """Return [(stroke, points)] for the drag strokes drawn at t.

        A stroke grows behind the pointer from the drag's start and stays,
        whole, until its "until" (by default the drag's end).
        """
        out = []
        for m in self.moves:
            s = m.get("stroke")
            if s and m["start"] <= t < s.get("until", m["end"]):
                out.append((s, polyline_prefix(m["path"], self.drag_progress(m, min(t, m["end"])))))
        return out

    def cursor_opacity(self, t):
        a = 1.0
        f = self.style["cursor_fade"]
        if self.cursor_fade_in is not None:
            a = min(a, smoothstep((t - self.cursor_fade_in) / f))
        if self.cursor_fade_out is not None:
            a = min(a, 1 - smoothstep((t - self.cursor_fade_out) / f))
        return a

    def state_at(self, t):
        """Return (image, previous image, mix) where mix is 0..1 toward image."""
        cur, prev = self.states[0], None
        for s in self.states[1:]:
            if t >= s["time"]:
                prev, cur = cur, s
        fade = cur.get("fade", 0)
        if prev is not None and fade > 0 and t < cur["time"] + fade:
            return cur["image"], prev["image"], smootherstep((t - cur["time"]) / fade)
        return cur["image"], None, 1.0

    def typing_at(self, t):
        """Return (box, progress) while a state's "type" text is being typed."""
        cur = self.states[0]
        for s in self.states[1:]:
            if t >= s["time"]:
                cur = s
        ty = cur.get("type")
        if not ty:
            return None
        p = (t - cur["time"]) / ty.get("duration", 2.0)
        return (ty["box"], p, cur["image"]) if p < 1 else None

    def keys_at(self, t):
        """Return [(text, opacity)] for the key badges showing at t.

        A badge fades in from its start and is gone by its end, so a badge
        that starts where the last one ends never shows over it.
        """
        f = self.style["key_fade"]
        out = []
        for k in self.keys:
            a = min(smoothstep((t - k["start"]) / f), 1 - smoothstep((t - k["end"] + f) / f))
            if a > 0:
                out.append((k["text"], a))
        return out


class Renderer:
    def __init__(self, scene, width):
        self.sc = scene
        self.W = int(width)
        self.H = int(round(width * scene.size[1] / scene.size[0]))
        self.k = self.W / 3840.0          # style scale
        self.sprites = self._cursor_sprites()
        self.badges = {}

    def _cursor_sprites(self, phases=4, ss=4):
        """Pre-render the pointer at sub-pixel offsets. Returns dict and origin."""
        st = self.sc.style
        k = self.k * st["cursor_size"] / 76.0
        pad = int(math.ceil(30 * self.k)) + 4
        box = int(math.ceil(95 * k)) + 2 * pad
        sprites = {}
        for py in range(phases):
            for px in range(phases):
                ox, oy = pad + px / phases, pad + py / phases
                S = box * ss
                pts = [((ox + x * k) * ss, (oy + y * k) * ss) for x, y in ARROW]
                fill = Image.new("L", (S, S), 0)
                ImageDraw.Draw(fill).polygon(pts, fill=255)
                ow = st["cursor_outline_width"] * self.k * ss
                outer = fill.filter(ImageFilter.MaxFilter(_odd(2 * ow)))
                fill = fill.resize((box, box), Image.LANCZOS)
                outer = outer.resize((box, box), Image.LANCZOS)
                sdx, sdy = (v * self.k for v in st["shadow_offset"])
                shadow = Image.new("L", (box, box), 0)
                shadow.paste(outer, (int(round(sdx)), int(round(sdy))))
                shadow = shadow.filter(ImageFilter.GaussianBlur(st["shadow_blur"] * self.k))
                f = np.asarray(fill, np.float32) / 255
                o = np.asarray(outer, np.float32) / 255
                s = np.asarray(shadow, np.float32) / 255 * st["shadow_opacity"]
                # Premultiplied layers: shadow, then white outline, then dark fill.
                col_o = np.array(st["cursor_outline"], np.float32)
                col_f = np.array(st["cursor_fill"], np.float32)
                P = np.zeros((box, box, 3), np.float32)
                A = s
                P = col_o * o[..., None] + P * (1 - o[..., None])
                A = o + A * (1 - o)
                P = col_f * f[..., None] + P * (1 - f[..., None])
                A = f + A * (1 - f)
                sprites[(px, py)] = (P, A)
        return {"phases": phases, "pad": pad, "box": box, "sprites": sprites}

    def clamp(self, cam):
        """Keep the view inside the capture."""
        x, y, z = cam
        w, h = self.sc.size[0] / z, self.sc.size[1] / z
        return (min(max(x, w / 2), self.sc.size[0] - w / 2),
                min(max(y, h / 2), self.sc.size[1] - h / 2), z)

    def to_screen(self, p, cam):
        x, y, z = cam
        sx = (p[0] - x) * z + self.sc.size[0] / 2
        sy = (p[1] - y) * z + self.sc.size[1] / 2
        return sx * self.W / self.sc.size[0], sy * self.H / self.sc.size[1]

    def background(self, name, cam, strokes=()):
        x, y, z = cam
        w, h = self.sc.size[0] / z, self.sc.size[1] / z
        im = self.sc.images[name]
        if strokes:
            # drawn on the still in native pixels, as the field draws its
            # live line, so the camera scales still and stroke together
            im = im.copy()
            draw = ImageDraw.Draw(im)
            for s, points in strokes:
                draw.line(points, fill=tuple(s["color"]), width=int(s["width"]), joint="curve")
        out = im.resize((self.W, self.H), Image.LANCZOS, box=(x - w / 2, y - h / 2, x + w / 2, y + h / 2))
        return np.asarray(out, np.float32)

    def frame(self, t):
        sc, st = self.sc, self.sc.style
        cam = self.clamp(sc.camera_at(t))
        img, prev, mix = sc.state_at(t)
        strokes = sc.strokes_at(t)
        f = self.background(img, cam, strokes)
        if prev is not None:
            f = self.background(prev, cam, strokes) * (1 - mix) + f * mix
        typing = sc.typing_at(t)
        if typing:
            self._typing(f, cam, *typing)
        cx, cy = self.to_screen(sc.cursor_at(t), cam)
        # Click rings
        for c in sc.clicks:
            age = t - c
            if 0 <= age < st["ring_duration"]:
                p = age / st["ring_duration"]
                hold = st["ring_hold"] / st["ring_duration"]
                r = st["ring_start_radius"] + (st["ring_end_radius"] - st["ring_start_radius"]) * smoothstep((p - hold) / (1 - hold))
                alpha = st["ring_opacity"] * (1 - p) ** 1.1
                self._ring(f, (cx, cy), r * self.k, st["ring_width"] * self.k, alpha, st["ring_color"])
        op = sc.cursor_opacity(t)
        if op > 0:
            self._cursor(f, cx, cy, op)
        for text, a in sc.keys_at(t):
            self._badge(f, text, a)
        return np.clip(f + 0.5, 0, 255).astype(np.uint8)

    def _typing(self, f, cam, box, p, image):
        """Hide the typed text right of the caret, then draw the caret."""
        x0, y0, x1, y1 = box
        im = self.sc.images[image]
        fill = np.array(im.getpixel((min(x1 + 2, im.size[0] - 1), y0)), np.float32)
        reveal = x0 + (x1 - x0) * max(p, 0.0)
        sx0, sy0 = self.to_screen((reveal, y0), cam)
        sx1, sy1 = self.to_screen((x1, y1), cam)
        X0, Y0 = max(int(math.floor(sx0)), 0), max(int(math.floor(sy0)), 0)
        X1, Y1 = min(int(math.ceil(sx1)), self.W), min(int(math.ceil(sy1)), self.H)
        if X0 < X1 and Y0 < Y1:
            f[Y0:Y1, X0:X1] = fill
            cw = max(1, int(round(3 * self.k * cam[2])))
            f[Y0:Y1, X0:min(X0 + cw, self.W)] = np.array(self.sc.style["cursor_fill"], np.float32)

    def _ring(self, f, c, r, w, alpha, color):
        R = int(math.ceil(r + w + 2))
        x0, y0 = int(c[0]) - R, int(c[1]) - R
        x1, y1 = x0 + 2 * R + 1, y0 + 2 * R + 1
        X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x1, self.W), min(y1, self.H)
        if X0 >= X1 or Y0 >= Y1:
            return
        yy, xx = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
        d = np.hypot(xx + 0.5 - c[0], yy + 0.5 - c[1])
        m = np.clip(w / 2 + 0.5 - np.abs(d - r), 0, 1) * alpha
        reg = f[Y0:Y1, X0:X1]
        reg += (np.array(color, np.float32) - reg) * m[..., None]

    def _badge(self, f, text, op):
        """Draw a key badge, for example "⇧ Shift", at the bottom center."""
        if text not in self.badges:
            from PIL import ImageFont
            st, k = self.sc.style, self.k
            size = max(8, int(round(st["key_font_size"] * k)))
            try:
                font = ImageFont.truetype(st["key_font"], size)
            except OSError:  # not on macOS: Pillow's own font, which has no key symbols
                font = ImageFont.load_default(size)
            try:
                font.set_variation_by_name("Semibold")
            except (OSError, ValueError):
                pass
            l, t0, r, b = font.getbbox(text)
            px, py = st["key_pad"][0] * k, st["key_pad"][1] * k
            w, h = int(math.ceil(r - l + 2 * px)), int(math.ceil(b - t0 + 2 * py))
            ss = 4
            shape = Image.new("L", (w * ss, h * ss), 0)
            ImageDraw.Draw(shape).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1),
                                                    radius=st["key_radius"] * k * ss, fill=255)
            shape = np.asarray(shape.resize((w, h), Image.LANCZOS), np.float32) / 255
            glyphs = Image.new("L", (w, h), 0)
            ImageDraw.Draw(glyphs).text((px - l, py - t0), text, font=font, fill=255)
            glyphs = np.asarray(glyphs, np.float32) / 255
            a = shape * st["key_opacity"]
            rgb = np.array(st["key_fill"], np.float32) * a[..., None]
            rgb = np.array(st["key_text"], np.float32) * glyphs[..., None] + rgb * (1 - glyphs[..., None])
            a = glyphs + a * (1 - glyphs)
            self.badges[text] = (rgb, a)
        rgb, a = self.badges[text]
        h, w = a.shape
        x0 = (self.W - w) // 2
        y0 = self.H - int(round(self.sc.style["key_margin"] * self.k)) - h
        reg = f[y0:y0 + h, x0:x0 + w]
        reg[:] = reg * (1 - a[..., None] * op) + rgb * op

    def _cursor(self, f, cx, cy, op):
        cs = self.sprites
        n = cs["phases"]
        ix, iy = math.floor(cx), math.floor(cy)
        px = min(int((cx - ix) * n), n - 1)
        py = min(int((cy - iy) * n), n - 1)
        rgb, a = cs["sprites"][(px, py)]
        x0, y0 = ix - cs["pad"], iy - cs["pad"]
        b = cs["box"]
        X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + b, self.W), min(y0 + b, self.H)
        if X0 >= X1 or Y0 >= Y1:
            return
        sp = rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * op
        sa = a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0, None] * op
        f[Y0:Y1, X0:X1] = f[Y0:Y1, X0:X1] * (1 - sa) + sp


def _odd(v):
    n = int(round(v))
    return n + 1 if n % 2 == 0 else n


# Default timing for `draft`, in seconds, measured from the same reference.
DRAFT = {
    "zoom": 1.8,          # zoom while working
    "start_zoom": 1.6,    # zoom of the first and last frames
    "intro": 0.7,         # still time before the first move
    "move": 1.6,          # pointer move
    "drag": 2.0,          # press to release of a drag
    "pan": 1.2,           # camera pan to bring the next target into view
    "settle": 0.2,        # pointer rests before a click
    "react": 0.08,        # click to screen change
    "fade": 0.12,         # cross-fade for a screen change marked "fade"
    "gap": 0.1,           # screen change to the next step
    "outro_delay": 0.37,  # last screen change to pointer fade out
    "outro": 1.65,        # final zoom out
    "tail": 0.8,          # still time at the end
    "loop_fade": 0.4,     # a looping clip's fade back to its first screen
    "safe": 0.3,          # camera pans when a target is outside this part of the view
    "key_lead": 0.35,     # a key badge shows this long before the pointer arrives
    "key_hold": 0.5,      # and stays this long after the click
}


def draft(spec):
    """Build a full scene from a short list of steps. See README.md."""
    W, H = spec["size"]
    d = dict(DRAFT)
    d.update(spec.get("timing", {}))
    targets = spec.get("targets", {})

    def pt(p):
        if isinstance(p, str):
            t = targets[p]
            p = t["center"] if isinstance(t, dict) else t
        return [float(p[0]), float(p[1])]

    def path(p):
        return [pt(q) for q in (targets[p]["points"] if isinstance(p, str) else p)]

    def time_at(progress, ramp=0.1):
        """The time share of a drag at which `progress` of its path is covered."""
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if path_progress(mid, ramp) < progress else (lo, mid)
        return hi

    def clamp(c):
        w, h = W / c["zoom"], H / c["zoom"]
        c["x"] = round(min(max(c["x"], w / 2), W - w / 2), 1)
        c["y"] = round(min(max(c["y"], h / 2), H - h / 2), 1)
        return c

    def follow(cam, target, z):
        w, h = W / z, H / z
        bx, by = w * d["safe"], h * d["safe"]
        x = min(max(cam["x"], target[0] - bx), target[0] + bx)
        y = min(max(cam["y"], target[1] - by), target[1] + by)
        return clamp({"x": x, "y": y, "zoom": z})

    def key(t, c):
        camera.append({"time": round(t, 3), "x": c["x"], "y": c["y"], "zoom": c["zoom"]})

    def aim(st):
        """Where a step's pointer goes first: its target, or where its drag starts."""
        return path(st["drag"])[0] if "drag" in st else pt(st.get("click") or st.get("point"))

    steps = spec["steps"]
    first = aim(steps[0])
    cam = spec.get("camera_start") or follow({"x": W / 2, "y": H / 2}, first, d["start_zoom"])
    cam = clamp(dict(cam))
    cursor = pt(spec.get("cursor_start", [first[0] + 500, first[1] + 520]))
    scene = {"size": [W, H], "images": spec["images"], "targets": targets,
             "cursor_start": cursor}
    if "cursor_size" in spec:
        scene["cursor_size"] = spec["cursor_size"]
    if "style" in spec:
        scene["style"] = spec["style"]
    states = [{"time": 0, "image": steps[0]["image"]}]
    camera, moves, clicks, keys = [], [], [], []
    key(0, cam)
    t = d["intro"]
    bend = 1
    for i, st in enumerate(steps):
        target = aim(st)
        z = st.get("zoom", d["zoom"])
        new = clamp(dict(st["camera"])) if "camera" in st else follow(cam, target, z)
        together = st.get("together", i == 0)
        if new != cam:
            key(t, cam)
            key(t + (d["move"] if together else d["pan"]), new)
            cam = new
            if not together:
                t += d["pan"] + 0.05
        dx, dy = target[0] - cursor[0], target[1] - cursor[1]
        dist = math.hypot(dx, dy)
        if dist > 1:
            nx, ny = -dy / dist * bend, dx / dist * bend
            k = 0.12 * dist
            moves.append({"start": round(t, 3), "end": round(t + st.get("move", d["move"]), 3), "to": target,
                          "controls": [[round(cursor[0] + dx * 0.3 + nx * k), round(cursor[1] + dy * 0.3 + ny * k)],
                                       [round(cursor[0] + dx * 0.75 + nx * k / 2), round(cursor[1] + dy * 0.75 + ny * k / 2)]]})
            bend = -bend
            t += st.get("move", d["move"])
        cursor = target
        key_start = t - d["key_lead"]
        t += st.get("dwell", 0)
        nxt = steps[i + 1]["image"] if i + 1 < len(steps) else st.get("after")
        shown = st["image"]
        stroke = None
        if "click" in st:
            t += d["settle"]
            clicks.append(round(t, 3))
            t += d["react"]
        if "drag" in st:
            # the press, the pointer along the path at an even speed, the release
            t += d["settle"]
            clicks.append(round(t, 3))
            span = st.get("drag_time", d["drag"])
            m = {"start": round(t, 3), "end": round(t + span, 3), "path": path(st["drag"])}
            if "stroke" in st:
                stroke = m["stroke"] = {**st["stroke"], "until": m["end"]}
            moves.append(m)
            # "frames" show in turn as the pointer covers equal shares of the
            # path, each from halfway between its share and the one before
            frames = st.get("frames", [])
            for k, name in enumerate(frames, 1):
                states.append({"time": round(t + span * time_at((k - 0.5) / len(frames)), 3), "image": name})
                shown = name
            t += span + d["react"]
            cursor = m["path"][-1]
        if "keys" in st:
            if keys and keys[-1]["end"] > key_start:  # one badge at a time
                keys[-1]["end"] = round(key_start, 3)
            keys.append({"start": round(key_start, 3), "end": round(t + d["key_hold"], 3), "text": st["keys"]})
        if nxt and nxt != shown:
            s = {"time": round(t, 3), "image": nxt}
            fade = steps[i + 1].get("fade") if i + 1 < len(steps) else st.get("after_fade")
            if fade:
                s["fade"] = d["fade"] if fade is True else fade
            if i + 1 < len(steps) and "type" in steps[i + 1]:
                s["type"] = steps[i + 1]["type"]
            states.append(s)
            if stroke:
                # the line stays until the next screen, which holds it, has
                # fully shown, so it never blinks away at the release
                stroke["until"] = round(s["time"] + s.get("fade", 0), 3)
        t += d["gap"] if i + 1 < len(steps) else 0
        if i + 1 < len(steps) and "type" in steps[i + 1]:
            t += steps[i + 1]["type"].get("duration", 2.0) + 0.3
    t += st.get("end_dwell", 0)
    scene["cursor_fade_out"] = round(t + d["outro_delay"], 3)
    end = clamp(dict(spec["camera_end"])) if "camera_end" in spec else follow(cam, cursor, d["start_zoom"])
    if spec.get("loop"):
        # a loop ends on its opening view, so its first frame follows its last
        end = {k: camera[0][k] for k in ("x", "y", "zoom")}
    key(t + 0.22, cam)
    key(t + 0.22 + d["outro"], end)
    duration = math.ceil((t + 0.22 + d["outro"] + d["tail"]) * 10) / 10
    loop = spec.get("loop")
    if loop:
        # a clip that plays on a loop: the pointer fades in at the start, and
        # once it has faded out and every fade has finished (a stroke ends
        # with the fade of the screen after it), the first screen fades
        # back, so the loop has no jump
        scene["cursor_fade_in"] = 0
        gone = scene["cursor_fade_out"] + {**STYLE, **spec.get("style", {})}["cursor_fade"]
        settled = max([gone] + [st["time"] + st.get("fade", 0) for st in states])
        duration = max(duration, math.ceil((settled + d["tail"]) * 10) / 10)
        if states[-1]["image"] != states[0]["image"]:
            fade = d["loop_fade"] if loop is True else loop
            at = round(settled + 0.1, 3)
            states.append({"time": at, "image": states[0]["image"], "fade": fade})
            duration = max(duration, math.ceil((at + fade + d["tail"]) * 10) / 10)
    key(duration, end)
    scene.update(duration=duration, states=states, moves=moves, clicks=clicks, camera=camera)
    if keys:
        scene["keys"] = keys
    return scene


def cmd_draft(a):
    spec_path = Path(a.steps)
    scene = draft(json.loads(spec_path.read_text()))
    out = Path(a.output) if a.output else spec_path.with_name("scene.json")
    out.write_text(json.dumps(scene, indent=2) + "\n")
    print(f"{out}: {scene['duration']} s, {len(scene['clicks'])} clicks")


def frame_count(scene):
    return int(round(scene.duration * scene.fps))


def cmd_render(a):
    sc = Scene(a.scene)
    r = Renderer(sc, a.width)
    n = frame_count(sc)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{r.W}x{r.H}", "-r", str(sc.fps), "-i", "-", "-an",
           "-c:v", "libx264", "-preset", sc.style["preset"], "-crf", str(a.crf if a.crf is not None else sc.style["crf"]),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(r.frame(i / sc.fps).tobytes())
        if i % sc.fps == 0:
            print(f"\r{out.name}: {i}/{n} frames", end="", file=sys.stderr, flush=True)
    p.stdin.close()
    if p.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"\r{out.name}: {n}/{n} frames", file=sys.stderr)


def cmd_still(a):
    sc = Scene(a.scene)
    r = Renderer(sc, a.width)
    Image.fromarray(r.frame(a.time)).save(a.output)


def cmd_sheet(a):
    sc = Scene(a.scene)
    r = Renderer(sc, 640)
    times = list(range(int(math.ceil(sc.duration))))
    cols = 3
    rows = math.ceil(len(times) / cols)
    th = r.H + 28
    sheet = Image.new("RGB", (cols * 640, rows * th), (245, 244, 240))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(times):
        x, y = (i % cols) * 640, (i // cols) * th
        d.text((x + 8, y + 8), f"{t} seconds", fill=(40, 40, 40))
        sheet.paste(Image.fromarray(r.frame(float(t))), (x, y + 28))
    sheet.save(a.output, quality=90)


def decode(path, w, h):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-"], stdout=subprocess.PIPE)
    size = w * h * 3
    while True:
        b = p.stdout.read(size)
        if len(b) < size:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
    p.wait()


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                          "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"width": s["width"], "height": s["height"], "fps": round(int(num) / int(den), 3),
            "frames": int(s["nb_read_frames"]), "duration": round(float(j["format"]["duration"]), 3)}


def cmd_compare(a):
    pa, pb = probe(a.a), probe(a.b)
    w, h = 960, 540
    psnrs, worst = [], (99, -1)
    for i, (fa, fb) in enumerate(zip(decode(a.a, w, h), decode(a.b, w, h))):
        mse = np.mean((fa.astype(np.float32) - fb.astype(np.float32)) ** 2)
        p = 99.0 if mse == 0 else 10 * math.log10(255 ** 2 / mse)
        psnrs.append(p)
        if p < worst[0]:
            worst = (p, i)
    ps = np.array(psnrs)
    res = {"a": pa, "b": pb, "compared_frames": len(ps), "compared_at": f"{w}x{h}",
           "psnr_mean": round(float(ps.mean()), 2), "psnr_median": round(float(np.median(ps)), 2),
           "psnr_min": round(float(ps.min()), 2), "worst_frame": worst[1],
           "frames_below_30db": int((ps < 30).sum()), "frames_below_35db": int((ps < 35).sum())}
    if a.per_second:
        fps = pa["fps"]
        res["psnr_by_second"] = [round(float(ps[int(s * fps):int((s + 1) * fps)].mean()), 1)
                                 for s in range(int(len(ps) / fps))]
    print(json.dumps(res, indent=2))


def cmd_mask(a):
    im = Image.open(a.input).convert("RGB")
    d = ImageDraw.Draw(im)
    color = tuple(a.color) if a.color else STYLE["mask_color"]
    for b in a.box:
        d.rectangle(b, fill=color)   # inclusive x0 y0 x1 y1
    im.save(a.output)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_verify(a):
    sc = Scene(a.scene)
    res = {"composition": "Still screen captures with a drawn pointer, click rings and camera. Not a continuous screen recording.",
           "scene": sc.path.name, "videos": {}, "sources": {}}
    for v in a.videos:
        info = probe(v)
        info.update(bytes=Path(v).stat().st_size, sha256=sha256(v))
        expect = frame_count(sc)
        info["frames_ok"] = info["frames"] == expect
        res["videos"][Path(v).name] = info
    for k, rel in sc.data["images"].items():
        p = sc.path.parent / rel
        res["sources"][k] = {"path": rel, "size": list(sc.images[k].size), "sha256": sha256(p)}
    out = sc.path.parent / "verification.json"
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render"); p.add_argument("scene"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--crf", type=int, help="H.264 quality, lower is better (default: STYLE crf, 17)")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("still"); p.add_argument("scene"); p.add_argument("-t", "--time", type=float, required=True)
    p.add_argument("-o", "--output", required=True); p.add_argument("--width", type=int, default=1920); p.set_defaults(fn=cmd_still)
    p = sub.add_parser("sheet"); p.add_argument("scene"); p.add_argument("-o", "--output", required=True); p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("compare"); p.add_argument("a"); p.add_argument("b")
    p.add_argument("--per-second", action="store_true"); p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("mask"); p.add_argument("input"); p.add_argument("output")
    p.add_argument("--box", type=int, nargs=4, action="append", required=True, metavar=("X0", "Y0", "X1", "Y1"))
    p.add_argument("--color", type=int, nargs=3); p.set_defaults(fn=cmd_mask)
    p = sub.add_parser("draft"); p.add_argument("steps"); p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_draft)
    p = sub.add_parser("verify"); p.add_argument("scene"); p.add_argument("videos", nargs="+"); p.set_defaults(fn=cmd_verify)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

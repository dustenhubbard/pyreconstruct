#!/usr/bin/env python3
"""Render an authored cursor and camera over captured stills. No app imports."""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

FPS = 60


def ease(value):
    """Smoothstep has zero velocity at both ends."""
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def number(value, name, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value < minimum):
        raise ValueError(f"{name} must be a finite number >= {minimum}")
    return value


def point(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must contain two coordinates")
    for coordinate in value:
        number(coordinate, name)


def validate(data):
    """Reject ambiguous timelines and invalid geometry before starting FFmpeg."""
    point(data["size"], "size")
    if any(int(v) != v or v < 2 for v in data["size"]):
        raise ValueError("size must contain positive integer dimensions >= 2")
    duration = number(data["duration"], "duration", 1 / FPS)
    if not math.isclose(duration * FPS, round(duration * FPS), abs_tol=1e-8):
        raise ValueError("duration must span a whole number of frames at 60 fps")
    number(data["cursor_size"], "cursor_size", 1)
    point(data["cursor_start"], "cursor_start")
    if not isinstance(data["images"], dict) or not data["images"]:
        raise ValueError("images must be a nonempty mapping of names to paths")
    if any(not isinstance(p, str) or not p for p in data["images"].values()):
        raise ValueError("image paths must be nonempty strings")
    for field in ("states", "camera"):
        keys = data[field]
        if not keys or keys[0]["time"] != 0:
            raise ValueError(f"{field} must start at time 0")
        previous = -1
        for key in keys:
            time = number(key["time"], f"{field}.time")
            if time <= previous or time > duration:
                raise ValueError(f"{field} times must increase within duration")
            previous = time
    for index, state in enumerate(data["states"]):
        if state["image"] not in data["images"]:
            raise ValueError(f"unknown state image: {state['image']}")
        fade = number(state.get("fade", 0), "state.fade")
        end = (data["states"][index + 1]["time"]
               if index + 1 < len(data["states"]) else duration)
        if (index == 0 and fade) or state["time"] + fade > end:
            raise ValueError("state fades must finish before the next state or end")
    for key in data["camera"]:
        number(key["x"], "camera.x")
        number(key["y"], "camera.y")
        number(key["zoom"], "camera.zoom", 1)
    previous = 0
    for move in data["moves"]:
        start = number(move["start"], "move.start")
        end = number(move["end"], "move.end")
        if start < previous or end <= start or end > duration:
            raise ValueError("moves must be ordered, nonoverlapping, and within duration")
        point(move["to"], "move.to")
        if len(move["controls"]) != 2:
            raise ValueError("moves need two cubic Bezier control points")
        for control in move["controls"]:
            point(control, "move.controls")
        previous = end
    previous = -1
    for click in data["clicks"]:
        number(click, "click")
        if click <= previous or click >= duration:
            raise ValueError("click times must increase and precede duration")
        previous = click
    if "cursor_fade_out" in data:
        number(data["cursor_fade_out"], "cursor_fade_out")


def cursor_position(data, time):
    start = data["cursor_start"]
    for move in data["moves"]:
        if time < move["start"]:
            break
        if time >= move["end"]:
            start = move["to"]
            continue
        u = ease((time - move["start"]) / (move["end"] - move["start"]))
        points = [start, *move["controls"], move["to"]]
        weights = [(1-u)**3, 3*(1-u)**2*u, 3*(1-u)*u*u, u**3]
        return tuple(sum(p[axis] * w for p, w in zip(points, weights))
                     for axis in (0, 1))
    return tuple(start)


def camera_box(data, time):
    keys = data["camera"]
    camera = keys[-1]
    for left, right in zip(keys, keys[1:]):
        if time < right["time"]:
            u = ease((time - left["time"]) / (right["time"] - left["time"]))
            camera = {k: left[k] + (right[k] - left[k]) * u
                      for k in ("x", "y", "zoom")}
            break
    width, height = data["size"]
    crop_w, crop_h = width / camera["zoom"], height / camera["zoom"]
    x = max(0, min(width - crop_w, camera["x"] - crop_w / 2))
    y = max(0, min(height - crop_h, camera["y"] - crop_h / 2))
    return x, y, x + crop_w, y + crop_h


def pointer_sprite(height):
    """Return an antialiased arrow and its tip offset, in output pixels."""
    scale = 3
    pad = max(4, round(height * .16))
    size = (math.ceil(height * .8) + 2 * pad, math.ceil(height) + 2 * pad)
    arrow = Image.new("RGBA", tuple(v * scale for v in size))
    points = [(0, 0), (.05, .79), (.25, .61), (.43, 1),
              (.59, .92), (.41, .55), (.72, .54)]
    points = [((x * height + pad) * scale, (y * height + pad) * scale)
              for x, y in points]
    draw = ImageDraw.Draw(arrow)
    draw.polygon(points, fill=(28, 28, 30, 255))
    draw.line(points + [points[0]], fill="white",
              width=max(2, round(height * .035 * scale)), joint="curve")
    shadow = Image.new("RGBA", arrow.size, (0, 0, 0, 0))
    alpha = arrow.getchannel("A").filter(ImageFilter.GaussianBlur(height * .04 * scale))
    shadow.putalpha(alpha.point(lambda a: round(a * .35)))
    shadow.alpha_composite(arrow, (0, 0))
    return shadow.resize(size, Image.Resampling.LANCZOS), pad


class Scene:
    def __init__(self, path, width):
        path = Path(path)
        self.data = json.loads(path.read_text())
        validate(self.data)
        height = width * self.data["size"][1] / self.data["size"][0]
        if width < 2 or width % 2 or not height.is_integer() or int(height) % 2:
            raise ValueError("output must have even dimensions and preserve the scene aspect ratio")
        self.size = (width, int(height))
        self.frames = round(self.data["duration"] * FPS)
        self.images = {}
        for name, relative in self.data["images"].items():
            with Image.open(path.parent / relative) as source:
                if source.size != tuple(self.data["size"]):
                    raise ValueError(f"{relative}: dimensions differ from scene size")
                self.images[name] = source.convert("RGB")
        self.pointer_height = width / self.data["size"][0] * self.data["cursor_size"]
        self.pointer, self.pointer_pad = pointer_sprite(self.pointer_height)

    def frame(self, time):
        data = self.data
        box = camera_box(data, time)
        index = 0
        for i, state in enumerate(data["states"]):
            if state["time"] > time:
                break
            index = i
        state = data["states"][index]

        def crop(name):
            return self.images[name].resize(self.size, Image.Resampling.BICUBIC, box=box)

        frame = crop(state["image"])
        fade = state.get("fade", 0)
        if fade and time < state["time"] + fade:
            frame = Image.blend(crop(data["states"][index - 1]["image"]), frame,
                                ease((time - state["time"]) / fade))
        zoom_scale = self.size[0] / (box[2] - box[0])

        def screen(position):
            return ((position[0] - box[0]) * zoom_scale,
                    (position[1] - box[1]) * zoom_scale)

        for click in data["clicks"]:
            age = time - click
            if 0 <= age < .45:
                radius = self.pointer_height * (.22 + .65 * ease(age / .45))
                side = math.ceil(radius * 2 + 8)
                pulse = Image.new("RGBA", (side * 3, side * 3))
                ImageDraw.Draw(pulse).ellipse(
                    (6, 6, (side - 2) * 3, (side - 2) * 3),
                    outline=(70, 110, 155, round(150 * (1 - age / .45))),
                    width=max(3, round(self.pointer_height * .04 * 3)))
                pulse = pulse.resize((side, side), Image.Resampling.LANCZOS)
                x, y = screen(cursor_position(data, click))
                frame.paste(pulse, (round(x - side / 2), round(y - side / 2)), pulse)
        opacity = 1 - ease((time - data.get("cursor_fade_out", data["duration"])) / .4)
        if opacity:
            pointer = self.pointer
            if opacity < 1:
                pointer = pointer.copy()
                pointer.putalpha(pointer.getchannel("A").point(lambda a: round(a * opacity)))
            x, y = screen(cursor_position(data, time))
            frame.paste(pointer, (round(x - self.pointer_pad), round(y - self.pointer_pad)), pointer)
        return frame


def render(scene, output, ffmpeg):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cursor-render-", dir=output.parent) as scratch:
        temporary = Path(scratch) / "video.mp4"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                   "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size",
                   f"{scene.size[0]}x{scene.size[1]}", "-framerate", str(FPS),
                   "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium",
                   "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                   str(temporary)]
        with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
            try:
                for index in range(scene.frames):
                    encoder.stdin.write(scene.frame(index / FPS).tobytes())
                    if index % FPS == 0:
                        print(f"{index}/{scene.frames} frames", flush=True)
                encoder.stdin.close()
                if encoder.wait():
                    raise RuntimeError("FFmpeg failed; no output published")
            except BaseException:
                encoder.kill()
                encoder.wait()
                raise
        os.link(temporary, output)
    print(f"Wrote {output} ({scene.frames} frames at {FPS} fps)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    try:
        render(Scene(args.scene, args.width), args.output, args.ffmpeg)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"Render failed: {error}\n")


if __name__ == "__main__":
    main()

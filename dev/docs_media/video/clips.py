#!/usr/bin/env python3
"""Render the User Guide's clips from one capture run's frames.

    uv run --frozen --no-default-groups python dev/docs_media/video/clips.py <capture folder> [--guide]

<capture folder> is the --out folder of dev/docs_media/capture/capture.py,
with its stills and targets.json. Each clip in CLIPS is authored here from
those targets: where the pointer goes, when it clicks, which still shows when.
Its scene goes in <capture folder>/clips/<name>.json, its video beside it.
--guide also replaces the clips in docs/assets/videos/user-guide/.
`capture.py --clips` runs this after the shoot, so one command does both.

The clips are kept short and quiet, for a page that plays them on a loop
with no sound: each fades the pointer in, does one thing, and fades back to
its first still, which is also its poster.

The encode is pinned (CRF, preset, thread count), so the same stills give the
same bytes with the same FFmpeg build.
"""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dev.docs_media.video.render import Scene, render, validate  # noqa: E402

GUIDE_CLIPS = REPO / "docs" / "assets" / "videos" / "user-guide"
# Guide clips another script makes, so --guide leaves them:
# dev/docs_media/capture/walkthrough_3d.py shoots the section 11 clip.
NOT_MADE_HERE = {"11-add-to-scene.mp4"}

# 2240 x 1520 stills scale to 1904 x 1292 with no padding; 1920 wide would
# leave a sub-pixel black row at the top and bottom
CLIP_WIDTH = 1904
CRF = 23
THREADS = 4
CURSOR_SIZE = 44  # native pixels, the arrow's height
LOOP_FADE = 0.4  # the fade back to the first still at the end
STROKE_WIDTH = 2  # a one-point pen at 2x
MENU_ZOOM = 2.0  # close enough to read a menu at the page's width


def bend(start, end, amount=0.08):
    """Two Bezier controls for a gentle arc from `start` to `end`."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy) or 1
    nx, ny = -dy / length, dx / length
    lift = amount * length
    return [[round(start[0] + dx * f + nx * lift, 1), round(start[1] + dy * f + ny * lift, 1)]
            for f in (0.3, 0.7)]


def move(start, end, at, to):
    """A pointer move from `at` to `to` between two times, on a gentle arc."""
    return {"start": start, "end": end, "to": list(to), "controls": bend(at, to)}


def camera_key(time, center, zoom):
    return {"time": time, "x": center[0], "y": center[1], "zoom": zoom}


def midpoint(*points):
    return [round(sum(p[0] for p in points) / len(points)),
            round(sum(p[1] for p in points) / len(points))]


def rest_point(canvas, fx=0.62, fy=0.66):
    """Where the pointer starts, in the field and clear of the palettes."""
    return [round(canvas["width"] * fx), round(canvas["height"] * fy)]


def scene(canvas, images, duration, **rest):
    data = {"size": [canvas["width"], canvas["height"]], "duration": duration,
            "cursor_size": CURSOR_SIZE, "images": images, "cursor_fade_in": 0, **rest}
    validate(data)
    return data


def menu_clip(canvas, targets, title, row, frames, zoom, result_fade=0):
    """Open a menu bar menu, pick one row, show what it opens.

    `frames` names four stills: before, the menu open, the row highlighted,
    and the result, which cuts in, or fades in over `result_fade` seconds.
    """
    before, opened, hovered, result = frames
    title_at, row_at = targets[title]["center"], targets[row]["center"]
    start = rest_point(canvas, 0.55, 0.6)
    menu_view = midpoint(title_at, row_at)
    whole = [canvas["width"] / 2, canvas["height"] / 2]
    return {
        "images": {"before": before, "opened": opened, "hovered": hovered, "result": result},
        "cursor_start": start,
        "moves": [move(0.5, 1.4, start, title_at), move(1.9, 2.4, title_at, row_at)],
        "clicks": [1.5, 2.7],
        "states": [{"time": 0, "image": "before"},
                   {"time": 1.55, "image": "opened"},
                   {"time": 2.35, "image": "hovered"},
                   {"time": 2.8, "image": "result", "fade": result_fade}],
        "camera": [camera_key(0, whole, 1), camera_key(0.5, whole, 1),
                   camera_key(1.4, menu_view, zoom), camera_key(2.8, menu_view, zoom),
                   camera_key(3.6, whole, 1)],
    }


def loop_back(data, at):
    """End on the first still, so the loop has no jump: fade the pointer out,
    then fade the picture back."""
    data["cursor_fade_out"] = at
    data["states"].append({"time": round(at + 0.5, 3), "image": data["states"][0]["image"],
                           "fade": LOOP_FADE})
    return data


def open_series(canvas, targets):
    """File > Open series..., then the series on its first section.

    The file dialog is the system's and is not shot; the clip fades from the
    menu to the open series instead.
    """
    data = menu_clip(canvas, targets, "file_menu", "open_series_row",
                     ("04-welcome-series.png", "04-file-menu.png",
                      "04-file-menu-open-series.png", "04-series-open.png"), MENU_ZOOM,
                     result_fade=0.3)
    return scene(canvas, duration=6.0, **loop_back(data, 4.8))


def open_object_list(canvas, targets):
    """Lists > Object list, the list docks beside the field, and its close
    button puts the field back as it began, so it loops with no fade."""
    data = menu_clip(canvas, targets, "lists_menu", "object_list_row",
                     ("04-series-open.png", "09-lists-menu.png",
                      "09-lists-menu-object-list.png", "09-object-list-opened.png"), MENU_ZOOM)
    close = targets["object_list_close"]["center"]
    data["moves"].append(move(3.9, 4.6, targets["object_list_row"]["center"], close))
    data["clicks"].append(4.75)
    data["states"].append({"time": 4.8, "image": "before"})
    return scene(canvas, duration=5.8, cursor_fade_out=5.0, **data)


def draw_closed_trace(canvas, targets):
    """Pick Closed Trace, drag a loop, let go.

    During the drag the stroke is the thin live line. At release it cuts to
    the unselected trace, which is drawn the same way, and only then fades in
    the selection, so the line never jumps from thin to selected in one frame.
    """
    path = targets["draw_path"]["points"]
    button = targets["closed_trace_button"]["center"]
    start = rest_point(canvas, 0.67, 0.69)
    xs, ys = [p[0] for p in path], [p[1] for p in path]
    drawing = [round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2)]
    whole = [canvas["width"] / 2, canvas["height"] / 2]
    release = 5.1
    data = {
        "images": {"open": "04-series-open.png", "selected": "06-closed-trace-selected.png",
                   "plain": "06-closed-trace-drawn-plain.png", "drawn": "06-closed-trace-drawn.png"},
        "cursor_start": start,
        "moves": [move(0.4, 1.3, start, button), move(1.8, 2.8, button, path[0]),
                  {"start": 3.05, "end": 5.05, "path": path, "ease_fraction": 0.1,
                   "stroke": {"color": targets["draw_path"]["color"], "width": STROKE_WIDTH,
                              "until": release}}],
        "clicks": [1.4, 3.0],
        "states": [{"time": 0, "image": "open"},
                   {"time": 1.45, "image": "selected"},
                   {"time": release, "image": "plain"},
                   {"time": release + 0.15, "image": "drawn", "fade": 0.25}],
        "camera": [camera_key(0, whole, 1), camera_key(1.8, whole, 1),
                   camera_key(2.8, drawing, 1.6), camera_key(5.6, drawing, 1.6),
                   camera_key(6.4, whole, 1)],
    }
    return scene(canvas, duration=7.5, **loop_back(data, 6.2))


def move_between_sections(canvas, targets):
    """The section buttons: up to section 1, then down to section 0 again.

    It ends where it began, so it loops with no fade.
    """
    up = targets["next_section_button"]["center"]
    down = targets["previous_section_button"]["center"]
    start = rest_point(canvas)
    whole = [canvas["width"] / 2, canvas["height"] / 2]
    return scene(
        canvas, duration=4.8,
        images={"section0": "04-series-open.png", "section1": "05-next-section.png"},
        cursor_start=start,
        moves=[move(0.4, 1.2, start, up), move(2.5, 2.9, up, down)],
        clicks=[1.3, 3.1],
        states=[{"time": 0, "image": "section0"}, {"time": 1.35, "image": "section1"},
                {"time": 3.15, "image": "section0"}],
        camera=[camera_key(0, whole, 1)],
        cursor_fade_out=4.2,
    )


# file name: authoring function; the number is the guide section it sits in
CLIPS = {
    "04-open-series": open_series,
    "05-move-between-sections": move_between_sections,
    "06-draw-closed-trace": draw_closed_trace,
    "09-open-object-list": open_object_list,
}


def poster(data):
    """The clip's first still, which the page shows before it plays."""
    return data["images"][data["states"][0]["image"]]


def scenes(targets_json):
    """Every clip's scene, from a capture run's targets.json contents."""
    canvas, targets = targets_json["canvas"], targets_json["targets"]
    return {name: author(canvas, targets) for name, author in CLIPS.items()}


def build(capture, names=None, guide=False, width=CLIP_WIDTH, ffmpeg="ffmpeg",
          guide_dir=GUIDE_CLIPS):
    """Write each clip's scene and video into <capture>/clips/; return the videos.

    With `guide`, the videos replace the ones in `guide_dir`, and a clip there
    that this run did not make is removed.
    """
    capture = Path(capture)
    out = capture / "clips"
    out.mkdir(exist_ok=True)
    made = []
    for name, data in scenes(json.loads((capture / "targets.json").read_text())).items():
        if names and name not in names:
            continue
        relative = {key: f"../{file}" for key, file in data["images"].items()}
        path = out / f"{name}.json"
        path.write_text(json.dumps({**data, "images": relative}, indent=2) + "\n")
        video = out / f"{name}.mp4"
        video.unlink(missing_ok=True)  # this run's own output; render will not overwrite
        render(Scene(path, width), video, ffmpeg, crf=CRF, threads=THREADS)
        made.append(video)
    if guide:
        copy_to_guide(made, guide_dir)
    return made


def copy_to_guide(videos, guide_dir=GUIDE_CLIPS):
    guide_dir.mkdir(parents=True, exist_ok=True)
    keep = {v.name for v in videos} | NOT_MADE_HERE
    for old in guide_dir.glob("*.mp4"):
        if old.name not in keep:
            old.unlink()
    for video in videos:
        shutil.copyfile(video, guide_dir / video.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("capture", type=Path, help="the capture script's --out folder")
    parser.add_argument("--guide", action="store_true",
                        help=f"also replace the clips in {GUIDE_CLIPS.relative_to(REPO)}")
    parser.add_argument("--only", nargs="*", choices=sorted(CLIPS), help="render only these")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    made = build(args.capture, args.only, args.guide and not args.only, ffmpeg=args.ffmpeg)
    for video in made:
        print(video)


if __name__ == "__main__":
    main()

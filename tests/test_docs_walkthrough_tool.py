"""The walkthrough renderer: a step list drafted into a scene, and one render.

dev/docs_media/walkthrough/walkthrough.py turns a short step list into a timed
scene and renders it over still captures. These tests check, on made-up
stills, that each click happens with the pointer on its target, that the next
screen shows only after the click, that key badges cover their click and
never overlap, that a camera kept at zoom 1 never moves, and that a render
has the frame count the scene asks for. For a drag: the press and release
land on the path's ends, the pointer keeps an even speed between its ramps,
a stroke grows up to the pointer and gives way at the release, and drag
frames change as the pointer covers the path. A looping clip fades the
pointer in and ends on its first screen.
"""

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "dev" / "docs_media" / "walkthrough" / "walkthrough.py"
STILL = {"x": 80, "y": 45, "zoom": 1}


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("docs_walkthrough", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def steps():
    return {
        "size": [160, 90],
        "images": {"a": "a.png", "b": "b.png", "c": "c.png"},
        "targets": {"one": [20, 10], "two": [120, 70], "three": [60, 40]},
        "camera_start": STILL,
        "camera_end": STILL,
        "steps": [
            {"image": "a", "click": "one", "camera": STILL},
            {"image": "b", "click": "two", "keys": "⇧ Shift", "camera": STILL},
            {"image": "b", "click": "three", "keys": "Right-click", "move": 0.4, "camera": STILL,
             "after": "c", "after_fade": 0.2},
        ],
    }


@pytest.fixture
def scene_file(tool, tmp_path):
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60)), ("c", (60, 60, 200))):
        Image.new("RGB", (160, 90), color).save(tmp_path / f"{name}.png")
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(tool.draft(steps())))
    return path


def test_each_click_lands_on_its_target(tool, scene_file):
    scene = tool.Scene(scene_file)
    targets = steps()["targets"]
    for when, name in zip(scene.clicks, ("one", "two", "three")):
        x, y = scene.cursor_at(when)
        assert math.hypot(x - targets[name][0], y - targets[name][1]) < 0.5, name


def test_the_next_screen_shows_only_after_the_click(tool, scene_file):
    scene = tool.Scene(scene_file)
    first, last = scene.clicks[0], scene.clicks[-1]
    assert scene.state_at(first - 0.01)[0] == "a"
    assert scene.state_at(first + 0.2)[0] == "b"
    assert scene.state_at(last - 0.01)[0] == "b"
    assert scene.state_at(last + 0.5)[0] == "c"


def test_key_badges_cover_their_click_and_never_overlap(tool, scene_file):
    data = json.loads(scene_file.read_text())
    keys = data["keys"]
    assert [k["text"] for k in keys] == ["⇧ Shift", "Right-click"]
    for key, click in zip(keys, data["clicks"][1:]):
        assert key["start"] < click < key["end"]
    assert keys[0]["end"] <= keys[1]["start"]


def test_a_camera_kept_at_zoom_1_never_moves(tool, scene_file):
    scene = tool.Scene(scene_file)
    for i in range(int(scene.duration * 10)):
        assert scene.camera_at(i / 10) == (80, 45, 1)


def test_a_render_has_the_frames_the_scene_asks_for(tool, scene_file, tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg is needed to render")
    video = tmp_path / "clip.mp4"
    subprocess.run([sys.executable, str(TOOL), "render", str(scene_file), "--width", "160",
                    "-o", str(video)], check=True, capture_output=True)
    scene = tool.Scene(scene_file)
    info = tool.probe(video)
    assert (info["width"], info["height"]) == (160, 90)
    assert info["frames"] == tool.frame_count(scene)


def test_only_one_key_badge_shows_at_a_time(tool, scene_file):
    # every frame, through the hand-over from one badge to the next
    scene = tool.Scene(scene_file)
    shown = [scene.keys_at(i / scene.fps) for i in range(tool.frame_count(scene))]
    assert all(len(badges) <= 1 for badges in shown)
    assert {text for badges in shown for text, _ in badges} == {"⇧ Shift", "Right-click"}


# --- drags --------------------------------------------------------------------

STROKE = [255, 0, 255]
# a path that turns a corner: 120 across, then 50 down
CORNER = [[20, 20], [140, 20], [140, 70]]


def drag_steps(**drag):
    return {
        "size": [160, 90],
        "images": {"a": "a.png", "b": "b.png", "c": "c.png",
                   "r1": "r1.png", "r2": "r2.png", "r3": "r3.png", "r4": "r4.png"},
        "targets": {"tool": [150, 80], "loop": {"points": CORNER}},
        "camera_start": STILL,
        "camera_end": STILL,
        "steps": [
            {"image": "a", "click": "tool", "camera": STILL},
            {"image": "b", "drag": "loop", "drag_time": 2.0, "camera": STILL, **drag},
            {"image": "c", "point": CORNER[-1], "camera": STILL},
        ],
    }


@pytest.fixture
def drag_scene(tool, tmp_path):
    def make(**drag):
        names = ("a", "b", "c", "r1", "r2", "r3", "r4")
        for i, name in enumerate(names):
            Image.new("RGB", (160, 90), (30 * i, 120, 200 - 20 * i)).save(tmp_path / f"{name}.png")
        path = tmp_path / "drag-scene.json"
        path.write_text(json.dumps(tool.draft(drag_steps(**drag))))
        return tool.Scene(path)
    return make


def the_drag(scene):
    return next(m for m in scene.moves if "path" in m)


def test_a_drag_presses_on_its_first_point_and_releases_on_its_last(drag_scene):
    scene = drag_scene()
    drag = the_drag(scene)
    press = scene.clicks[-1]
    assert press <= drag["start"]
    assert scene.cursor_at(press) == pytest.approx(CORNER[0])
    assert scene.cursor_at(drag["end"]) == pytest.approx(CORNER[-1])
    # the drag's screen holds until the release, and the next one follows it
    assert scene.state_at(drag["end"] - 0.01)[0] == "b"
    assert scene.state_at(drag["end"] + 0.2)[0] == "c"


def test_the_pointer_follows_the_path_at_an_even_speed_between_its_ramps(drag_scene):
    scene = drag_scene()
    drag = the_drag(scene)
    span = drag["end"] - drag["start"]
    # every position lies on the path: the top edge, then the right edge
    for i in range(1, 100):
        x, y = scene.cursor_at(drag["start"] + span * i / 100)
        assert y == pytest.approx(20) or x == pytest.approx(140), (x, y)
    # in the middle 80% of the time, equal times cover equal lengths of path
    length = 170
    covered = []
    for i in range(10, 90, 10):
        t0 = drag["start"] + span * i / 100
        t1 = drag["start"] + span * (i + 10) / 100
        a = scene.drag_progress(drag, t0) * length
        b = scene.drag_progress(drag, t1) * length
        covered.append(b - a)
    assert max(covered) - min(covered) < 1e-6
    # and it starts and stops gently
    assert scene.drag_progress(drag, drag["start"] + span * 0.05) * length < covered[0] / 2


def test_a_stroke_grows_behind_the_pointer_and_gives_way_at_the_release(drag_scene):
    scene = drag_scene(stroke={"color": STROKE, "width": 2})
    drag = the_drag(scene)
    assert drag["stroke"]["until"] == drag["end"]
    mid = (drag["start"] + drag["end"]) / 2
    (stroke, points), = scene.strokes_at(mid)
    assert points[0] == pytest.approx(CORNER[0])
    assert points[-1] == pytest.approx(scene.cursor_at(mid))
    assert scene.strokes_at(drag["start"] - 0.01) == []
    assert scene.strokes_at(drag["end"]) == []


def test_the_rendered_stroke_is_drawn_up_to_the_pointer_and_no_further(tool, drag_scene):
    scene = drag_scene(stroke={"color": STROKE, "width": 2})
    drag = the_drag(scene)
    mid = (drag["start"] + drag["end"]) / 2
    x, _ = scene.cursor_at(mid)
    assert 40 < x < 120
    frame = tool.Renderer(scene, 160).frame(mid)
    behind, ahead = frame[20, 30], frame[20, 135]
    assert abs(int(behind[0]) - 255) < 40 and int(behind[1]) < 60
    assert tuple(ahead) == tuple(frame[30, 135])  # the still, untouched


def test_drag_frames_show_in_turn_as_the_pointer_covers_the_path(drag_scene):
    frames = ["r1", "r2", "r3", "r4"]
    scene = drag_scene(frames=frames)
    drag = the_drag(scene)
    span = drag["end"] - drag["start"]
    seen = []
    for i in range(1, 200):
        t = drag["start"] + span * i / 200
        image = scene.state_at(t)[0]
        progress = scene.drag_progress(drag, t)
        # the frame showing is the one whose share of the path is nearest
        expect = "b" if progress < 0.125 else frames[min(int(progress * 4 + 0.5), 4) - 1]
        assert image == expect, (round(progress, 3), image)
        if not seen or seen[-1] != image:
            seen.append(image)
    assert seen == ["b", *frames]
    # the last frame holds through the release, then the next step's screen
    assert scene.state_at(drag["end"] + 0.01)[0] == "r4"
    assert scene.state_at(drag["end"] + 0.2)[0] == "c"


# --- loops --------------------------------------------------------------------


def test_a_looping_clip_ends_on_its_first_screen_after_the_pointer_is_gone(tool, tmp_path):
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60)), ("c", (60, 60, 200))):
        Image.new("RGB", (160, 90), color).save(tmp_path / f"{name}.png")
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(tool.draft({**steps(), "loop": 0.3})))
    scene = tool.Scene(path)
    last = scene.states[-1]
    assert last["image"] == "a" and last["fade"] == 0.3
    assert last["time"] >= scene.cursor_fade_out + scene.style["cursor_fade"]
    assert last["time"] + last["fade"] < scene.duration
    assert scene.state_at(scene.duration)[0] == "a"
    assert scene.cursor_opacity(0) == 0 and scene.cursor_opacity(0.5) == 1


def test_a_looping_clip_that_ends_where_it_began_adds_no_fade(tool, scene_file, tmp_path):
    spec = steps()
    spec["steps"][-1]["after"] = "a"
    path = tmp_path / "back.json"
    path.write_text(json.dumps(tool.draft({**spec, "loop": True})))
    scene = tool.Scene(path)
    assert [s["image"] for s in scene.states] == ["a", "b", "a"]

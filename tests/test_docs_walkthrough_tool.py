"""The walkthrough renderer: a step list drafted into a scene, and one render.

dev/docs_media/walkthrough/walkthrough.py turns a short step list into a timed
scene and renders it over still captures. These tests check, on made-up
stills, that each click happens with the pointer on its target, that the next
screen shows only after the click, that key badges cover their click and
never overlap, that a camera kept at zoom 1 never moves, and that a render
has the frame count the scene asks for.
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

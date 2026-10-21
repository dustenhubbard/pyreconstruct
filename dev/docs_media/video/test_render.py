"""Synthetic fixtures only; no captured application images belong in this tree."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageChops
import pytest

from dev.docs_media.video.render import Scene, camera_box, cursor_position, render, validate
from dev.docs_media.video.verify import contact_sheet, measure


@pytest.fixture
def scene_file(tmp_path):
    Image.new("RGB", (160, 90), "red").save(tmp_path / "red.png")
    Image.new("RGB", (160, 90), "blue").save(tmp_path / "blue.png")
    data = {"size": [160, 90], "duration": 2, "cursor_size": 12,
            "images": {"red": "red.png", "blue": "blue.png"},
            "states": [{"time": 0, "image": "red"},
                       {"time": 1, "image": "blue", "fade": .5}],
            "cursor_start": [10, 20],
            "moves": [{"start": .5, "end": 1.5, "to": [110, 20],
                       "controls": [[10, 60], [110, 60]]}],
            "clicks": [.3], "cursor_fade_out": 1.6,
            "camera": [{"time": 0, "x": 80, "y": 45, "zoom": 1}]}
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(data))
    return path


def test_cursor_eased_cubic_and_holds(scene_file):
    data = json.loads(scene_file.read_text())
    assert cursor_position(data, 0) == (10, 20)
    assert cursor_position(data, 1) == (60, 50)
    assert cursor_position(data, .75) == pytest.approx((16.561279296875, 35.8203125))
    assert cursor_position(data, 1.9) == (110, 20)


def test_camera_interpolates_and_clamps(scene_file):
    data = json.loads(scene_file.read_text())
    data["camera"] = [{"time": 0, "x": 0, "y": 0, "zoom": 2},
                      {"time": 2, "x": 160, "y": 90, "zoom": 2}]
    assert camera_box(data, 0) == (0, 0, 80, 45)
    assert camera_box(data, 1) == (40, 22.5, 120, 67.5)
    assert camera_box(data, 2) == (80, 45, 160, 90)


def test_frames_state_fade_and_cursor_fade(scene_file):
    scene = Scene(scene_file, 160)
    assert scene.frames == 120
    assert scene.frame(.9).getpixel((150, 80)) == (255, 0, 0)
    assert scene.frame(1.25).getpixel((150, 80)) == (127, 0, 127)
    assert scene.frame(1.5).getpixel((150, 80)) == (0, 0, 255)
    assert scene.frame(0).getpixel((12, 25)) != (255, 0, 0)
    assert ImageChops.difference(scene.frame(2), Image.new("RGB", (160, 90), "blue")).getbbox() is None


def test_click_stays_at_click_position_while_cursor_moves(scene_file):
    data = json.loads(scene_file.read_text())
    data["clicks"] = [.6]
    scene_file.write_text(json.dumps(data))
    clicked = Scene(scene_file, 160).frame(.85)
    data["clicks"] = []
    scene_file.write_text(json.dumps(data))
    plain = Scene(scene_file, 160).frame(.85)
    box = ImageChops.difference(clicked, plain).getbbox()
    assert box is not None
    assert box[0] < 10 and box[2] < 25


@pytest.mark.parametrize("field,value", [
    ("duration", float("nan")), ("duration", .123), ("cursor_size", 0),
    ("size", [160.5, 90]), ("clicks", [1, .5]), ("clicks", [2]),
    ("states", [{"time": .1, "image": "red"}]),
    ("states", [{"time": 0, "image": "missing"}]),
    ("camera", [{"time": 0, "x": 80, "y": 45, "zoom": .5}]),
])
def test_invalid_scene_rejected(scene_file, field, value):
    data = json.loads(scene_file.read_text())
    data[field] = value
    with pytest.raises(ValueError):
        validate(data)


def test_overlapping_moves_rejected(scene_file):
    data = json.loads(scene_file.read_text())
    data["moves"].append(copy.deepcopy(data["moves"][0]))
    with pytest.raises(ValueError, match="nonoverlapping"):
        validate(data)


def test_dimension_mismatch_and_odd_output_rejected(scene_file):
    with pytest.raises(ValueError, match="even dimensions"):
        Scene(scene_file, 159)
    Image.new("RGB", (80, 45)).save(scene_file.parent / "red.png")
    with pytest.raises(ValueError, match="dimensions differ"):
        Scene(scene_file, 160)


def test_cli_encode_decode_and_no_overwrite(scene_file, tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required for the encode/decode integration test")
    output = tmp_path / "test video.mp4"
    command = [sys.executable, str(Path(__file__).with_name("render.py")), str(scene_file),
               "--width", "160", "--output", str(output), "--ffmpeg", ffmpeg]
    subprocess.run(command, check=True, capture_output=True, cwd=tmp_path)
    info = measure(output, ffprobe)
    assert {key: info[key] for key in ("width", "height", "frames", "duration", "fps", "audio_streams", "codec")} == {
        "width": 160, "height": 90, "frames": 120, "duration": 2.0,
        "fps": "60/1", "audio_streams": 0, "codec": "h264"}
    sheet, _ = contact_sheet(output, info, ffmpeg)
    assert sheet.size == (1536, 312)
    assert sheet.getpixel((480, 280))[0] > 240
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode != 0
    assert "refusing to overwrite" in failed.stderr
    assert measure(output, ffprobe)["sha256"] == info["sha256"]


def test_failed_encoder_publishes_nothing(scene_file, tmp_path):
    output = tmp_path / "failed.mp4"
    with pytest.raises(FileNotFoundError):
        render(Scene(scene_file, 160), output, str(tmp_path / "missing-ffmpeg"))
    assert not output.exists()
    assert not list(tmp_path.glob(".cursor-render-*"))

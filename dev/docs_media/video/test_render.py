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


def test_dimension_mismatch_rejected(scene_file):
    Image.new("RGB", (80, 45)).save(scene_file.parent / "red.png")
    with pytest.raises(ValueError, match="dimensions differ"):
        Scene(scene_file, 160)


def test_exact_aspect_resize_preserves_legacy_sampling(scene_file):
    data = json.loads(scene_file.read_text())
    data.update(cursor_fade_out=0, clicks=[],
                camera=[{"time": 0, "x": 80, "y": 45, "zoom": 2}])
    scene_file.write_text(json.dumps(data))
    source = Image.new("RGB", (160, 90))
    source.putdata([((x * 17) % 256, (y * 31) % 256, (x * y) % 256)
                    for y in range(90) for x in range(160)])
    source.save(scene_file.parent / "red.png")
    expected = source.resize((224, 126), Image.Resampling.BICUBIC, box=(40, 22.5, 120, 67.5))
    assert ImageChops.difference(Scene(scene_file, 224).frame(.45), expected).getbbox() is None


@pytest.fixture
def drag_file(scene_file):
    data = json.loads(scene_file.read_text())
    data.update(cursor_start=[20, 20], clicks=[], cursor_fade_out=0,
                states=[{"time": 0, "image": "red"}],
                moves=[{"start": .5, "end": 1.5,
                        "path": [[20, 20], [40, 20], [40, 60], [100, 60]],
                        "ease_fraction": 0,
                        "stroke": {"color": [0, 255, 0], "width": 4, "until": 1.75}}])
    scene_file.write_text(json.dumps(data))
    return scene_file


def test_polyline_uses_distance_across_unequal_segments_and_holds(drag_file):
    data = json.loads(drag_file.read_text())
    assert cursor_position(data, 0) == (20, 20)
    assert cursor_position(data, .75) == pytest.approx((40, 30))
    assert cursor_position(data, 1) == pytest.approx((40, 60))
    assert cursor_position(data, 1.25) == pytest.approx((70, 60))
    assert cursor_position(data, 1.75) == (100, 60)


def test_polyline_eases_only_at_ends_with_constant_middle_speed(drag_file):
    data = json.loads(drag_file.read_text())
    move = data["moves"][0]
    move.pop("ease_fraction")
    move["path"] = [[20, 20], [30, 20], [70, 20], [120, 20]]
    # Default ramps occupy the first and last tenth of the move, regardless of vertices.
    assert cursor_position(data, .55) == pytest.approx((21.3888888889, 20))
    assert cursor_position(data, 1.45) == pytest.approx((118.6111111111, 20))
    assert [cursor_position(data, t)[0] for t in (.7, .8, .9, 1, 1.1, 1.2, 1.3)] == pytest.approx(
        [36.6666666667, 47.7777777778, 58.8888888889, 70, 81.1111111111, 92.2222222222, 103.3333333333])


def test_polyline_closed_loop_and_repeated_points(drag_file):
    data = json.loads(drag_file.read_text())
    data["moves"][0]["path"] = [[20, 20], [20, 20], [40, 20], [40, 40], [20, 40], [20, 20]]
    validate(data)
    assert cursor_position(data, .75) == (40, 20)
    assert cursor_position(data, 1) == (40, 40)
    assert cursor_position(data, 1.5) == (20, 20)


def test_drag_reveals_only_traveled_line_and_keeps_it_until_cut(drag_file):
    scene = Scene(drag_file, 160)
    assert scene.frame(.45).getpixel((30, 20)) == (255, 0, 0)
    halfway = scene.frame(1)
    assert halfway.getpixel((30, 20)) == (0, 255, 0)
    assert halfway.getpixel((40, 45)) == (0, 255, 0)
    assert halfway.getpixel((70, 60)) == (255, 0, 0)
    # No closing chord or fill is added during a freehand drag.
    assert halfway.getpixel((30, 40)) == (255, 0, 0)
    assert sum(halfway.getpixel((x, 45)) == (0, 255, 0) for x in range(30, 50)) == 4
    assert scene.frame(1.6).getpixel((70, 60)) == (0, 255, 0)
    assert scene.frame(1.75).getpixel((70, 60)) == (255, 0, 0)


def test_stroke_end_meets_cursor_and_transforms_with_camera_and_padding(drag_file):
    data = json.loads(drag_file.read_text())
    data["camera"] = [{"time": 0, "x": 60, "y": 45, "zoom": 2}]
    drag_file.write_text(json.dumps(data))
    scene = Scene(drag_file, 160, 130)
    frame = scene.frame(.75)
    # Viewport top is 20, crop is (20, 22.5, 100, 67.5), and the cursor is at (40, 30).
    assert cursor_position(data, .75) == (40, 30)
    assert frame.getpixel((40, 34)) == (0, 255, 0)
    assert frame.getpixel((40, 40)) == (255, 0, 0)
    assert frame.getpixel((40, 10)) == (0, 0, 0)
    assert sum(frame.getpixel((x, 30)) == (0, 255, 0) for x in range(25, 55)) >= 6


def test_completed_stroke_replaced_by_real_still_at_cut(drag_file):
    data = json.loads(drag_file.read_text())
    data["states"].append({"time": 1.75, "image": "blue"})
    drag_file.write_text(json.dumps(data))
    before = Scene(drag_file, 160).frame(1.6)
    assert before.getpixel((70, 60)) == (0, 255, 0)
    before.save(drag_file.parent / "blue.png")
    scene = Scene(drag_file, 160)
    assert ImageChops.difference(scene.frame(1.6), scene.frame(1.75)).getbbox() is None


def test_stroke_defaults_to_disappearing_at_release(drag_file):
    data = json.loads(drag_file.read_text())
    data["moves"][0]["stroke"].pop("until")
    drag_file.write_text(json.dumps(data))
    scene = Scene(drag_file, 160)
    assert scene.frame(1.4).getpixel((70, 60)) == (0, 255, 0)
    assert scene.frame(1.5).getpixel((70, 60)) == (255, 0, 0)


@pytest.mark.parametrize("width,height,expected", [
    (1920, None, (1920, 1304)), (1919, None, (1920, 1304)),
    (1, None, (2, 2)), (2240, None, (2240, 1520)),
    (1920, 1080, (1920, 1080)), (1919, 1079, (1920, 1080)),
])
def test_any_width_fits_even_frame_without_aspect_distortion(scene_file, width, height, expected):
    data = json.loads(scene_file.read_text())
    data.update(size=[224, 152], cursor_fade_out=0, clicks=[],
                camera=[{"time": 0, "x": 112, "y": 76, "zoom": 1}])
    for name in ("red", "blue"):
        Image.new("RGB", (224, 152), name).save(scene_file.parent / f"{name}.png")
    scene_file.write_text(json.dumps(data))
    scene = Scene(scene_file, width, height)
    assert scene.size == expected
    assert scene.frame(.45).size == expected
    if height is not None:
        frame = scene.frame(.45)
        assert frame.getpixel((160, 500)) == (0, 0, 0)
        assert frame.getpixel((165, 500)) == (255, 0, 0)
        assert frame.getpixel((1754, 500)) == (255, 0, 0)
        assert frame.getpixel((1760, 500)) == (0, 0, 0)


@pytest.mark.parametrize("width,height", [(0, None), (-2, None), (160, 0), (True, 90)])
def test_invalid_output_dimensions_rejected(scene_file, width, height):
    with pytest.raises(ValueError, match="positive integers"):
        Scene(scene_file, width, height)


@pytest.mark.parametrize("changes", [
    {"path": []}, {"path": [[20, 20], [20, 20]]},
    {"path": [[21, 20], [40, 20]]}, {"path": [[20, 20], [float("nan"), 20]]},
    {"to": [100, 60]}, {"controls": [[20, 20], [40, 20]]},
    {"ease_fraction": -.1}, {"ease_fraction": .51},
    {"stroke": {"color": [256, 0, 0], "width": 2}},
    {"stroke": {"color": [True, 0, 0], "width": 2}},
    {"stroke": {"color": [0, 0], "width": 2}},
    {"stroke": {"color": [0, 255, 0], "width": 0}},
    {"stroke": {"color": [0, 255, 0], "width": 1.5}},
    {"stroke": {"color": [0, 255, 0], "width": 2, "until": 1}},
    {"stroke": {"color": [0, 255, 0], "width": 2, "until": 3}},
])
def test_invalid_polyline_or_stroke_rejected(drag_file, changes):
    data = json.loads(drag_file.read_text())
    data["moves"][0].update(changes)
    with pytest.raises(ValueError):
        validate(data)


def test_cli_drag_in_padded_odd_frame(drag_file, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the encode/decode integration test")
    output = tmp_path / "drag.mp4"
    command = [sys.executable, str(Path(__file__).with_name("render.py")), str(drag_file),
               "--width", "159", "--height", "129", "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True)
    info = measure(output)
    assert (info["width"], info["height"], info["frames"]) == (160, 130, 120)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(output),
                                   "-vf", "select=eq(n\\,60)", "-frames:v", "1",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    frame = Image.frombytes("RGB", (160, 130), raw)
    assert max(frame.getpixel((80, 10))) < 10
    assert frame.getpixel((40, 65))[1] > 220
    assert frame.getpixel((70, 80))[0] > 220


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

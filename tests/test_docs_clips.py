"""The User Guide clips: how each is authored from a capture run's targets.

dev/docs_media/video/clips.py turns the capture script's targets.json into one
scene per clip and renders it. These tests check the scenes on made-up targets
(every click lands on its target, every clip loops back to its first still,
the drawn trace never jumps from the live stroke to its selected look in one
frame), that the stills a clip uses are ones the capture script shoots, and
that the guide's markup matches the clips. One small render checks that the
same stills give the same bytes.
"""

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

from dev.docs_media.video import clips
from dev.docs_media.video.render import cursor_position, validate
from tests.test_docs_capture import capture  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "docs" / "USER_GUIDE.md"
GUIDE_IMAGES = REPO / "docs" / "assets" / "images" / "user-guide"

CANVAS = {"width": 2240, "height": 1520, "origin": "top-left", "units": "native pixels"}


def made_up_targets(scale=1.0):
    """Targets shaped like a real run's, at `scale` times the native canvas."""
    def at(x, y):
        return [round(x * scale), round(y * scale)]

    loop = [at(812 + 140 * math.cos(t / 24 * math.pi) - 140, 760 + 100 * math.sin(t / 24 * math.pi))
            for t in range(49)]
    loop[-1] = loop[0]
    return {
        "canvas": {**CANVAS, "width": round(2240 * scale), "height": round(1520 * scale)},
        "targets": {
            "file_menu": {"center": at(48, 18)},
            "open_series_row": {"center": at(244, 98)},
            "closed_trace_button": {"center": at(2178, 502)},
            "draw_path": {"points": loop, "color": [255, 128, 64]},
            "next_section_button": {"center": at(2120, 1318)},
            "previous_section_button": {"center": at(2120, 1418)},
            "lists_menu": {"center": at(410, 18)},
            "object_list_row": {"center": at(560, 64)},
            "object_list_close": {"center": at(22, 84)},
        },
    }


@pytest.fixture
def scenes():
    return clips.scenes(made_up_targets())


# where each clip's clicks land, in order; "path start" is the press that
# starts the drag
CLICK_TARGETS = {
    "04-open-series": ["file_menu", "open_series_row"],
    "05-move-between-sections": ["next_section_button", "previous_section_button"],
    "06-draw-closed-trace": ["closed_trace_button", "path start"],
    "09-open-object-list": ["lists_menu", "object_list_row", "object_list_close"],
}


def test_every_clip_is_a_valid_scene_of_4_to_8_seconds(scenes):
    assert set(scenes) == set(CLICK_TARGETS)
    for name, data in scenes.items():
        validate(data)
        assert 4 <= data["duration"] <= 8, name


def test_every_click_lands_on_its_target(scenes):
    targets = made_up_targets()["targets"]
    for name, data in scenes.items():
        expected = [targets["draw_path"]["points"][0] if key == "path start"
                    else targets[key]["center"] for key in CLICK_TARGETS[name]]
        landed = [cursor_position(data, t) for t in data["clicks"]]
        assert len(landed) == len(expected), name
        for (x, y), (ex, ey) in zip(landed, expected):
            assert math.hypot(x - ex, y - ey) < 0.5, name


def test_every_clip_ends_on_its_first_still_with_no_pointer(scenes):
    for name, data in scenes.items():
        states = data["states"]
        last = states[-1]
        assert last["image"] == states[0]["image"], name
        assert last["time"] + last.get("fade", 0) < data["duration"], name
        # the pointer fades in from nothing and is gone before the loop
        assert data["cursor_fade_in"] == 0, name
        assert data["cursor_fade_out"] + 0.4 < data["duration"], name


def test_the_poster_is_the_first_still_and_a_guide_image(scenes):
    for name, data in scenes.items():
        assert clips.poster(data) == data["images"][data["states"][0]["image"]]
        assert (GUIDE_IMAGES / clips.poster(data)).is_file(), name


def test_a_drawn_trace_cuts_to_its_plain_look_before_the_selection_fades_in(scenes):
    data = scenes["06-draw-closed-trace"]
    drag = next(m for m in data["moves"] if "stroke" in m)
    by_image = {data["images"][s["image"]]: s for s in data["states"]}
    plain = by_image["06-closed-trace-drawn-plain.png"]
    drawn = by_image["06-closed-trace-drawn.png"]
    # the live stroke gives way to the unselected trace, drawn the same way...
    assert plain["time"] == drag["stroke"]["until"]
    assert plain.get("fade", 0) == 0
    # ...and only then does the selected look fade in
    assert drawn["time"] > plain["time"]
    assert drawn["fade"] >= 0.2


def test_the_live_stroke_has_the_traces_color_and_one_point_width(scenes):
    stroke = next(m for m in scenes["06-draw-closed-trace"]["moves"] if "stroke" in m)["stroke"]
    assert stroke["color"] == [255, 128, 64]
    assert stroke["width"] == 2


def test_a_menu_row_lights_up_when_the_pointer_reaches_it(scenes):
    targets = made_up_targets()["targets"]
    for name, row in (("04-open-series", "open_series_row"), ("09-open-object-list", "object_list_row")):
        data = scenes[name]
        hovered = next(s for s in data["states"] if s["image"] == "hovered")
        x, y = cursor_position(data, hovered["time"])
        cx, cy = targets[row]["center"]
        assert math.hypot(x - cx, y - cy) < 30, name


def test_every_still_a_clip_uses_is_a_guide_image_or_flow_only(scenes, capture):  # noqa: F811
    # a flow-only still is shot but kept out of the guide by --guide; any
    # other still a clip uses must be one the guide already shows
    for name, data in scenes.items():
        for image in data["images"].values():
            in_guide = (GUIDE_IMAGES / image).is_file()
            assert (Path(image).stem in capture.FLOW_ONLY) != in_guide, (name, image)


def test_the_guide_embeds_each_clip_with_its_poster_and_length(scenes):
    # each clip is its poster image and a link to its MP4, which
    # docs/javascripts/clips.js turns into the looping video
    figures = re.findall(r'<figure class="clip" markdown>(.*?)</figure>', GUIDE.read_text(), re.S)
    found = {}
    for figure in figures:
        link = re.search(r"\[▶ (\d+) s · loops\]\(assets/videos/user-guide/([^)]+)\.mp4\)"
                         r"\{ \.clip-src \}", figure)
        assert link, figure
        found[link.group(2)] = (int(link.group(1)), figure)
    assert set(found) == set(scenes)
    for name, (seconds, figure) in found.items():
        data = scenes[name]
        poster = re.search(r"!\[([^\]]+)\]\(assets/images/user-guide/([^)]+)\)", figure)
        assert poster.group(2) == clips.poster(data), name
        assert poster.group(1).startswith("Clip: "), name
        assert seconds == round(data["duration"]), name
        assert "<figcaption markdown>**" in figure, name
        assert (REPO / "docs" / "assets" / "videos" / "user-guide" / f"{name}.mp4").is_file(), name


def test_the_clip_script_is_on_the_site():
    config = (REPO / "mkdocs.yml").read_text()
    assert re.search(r"extra_javascript:\n  - javascripts/clips\.js\n", config)
    script = (REPO / "docs" / "javascripts" / "clips.js").read_text()
    for needed in ("figure.clip", "a.clip-src", "prefers-reduced-motion: reduce", "playsInline",
                   'preload = "metadata"', "video.muted = true", "video.loop = true", "Replay"):
        assert needed in script, needed
    assert "controls" not in script


# --- one small render -------------------------------------------------------


@pytest.fixture
def small_capture(tmp_path):
    """A capture folder of made-up stills at a tenth of the native size."""
    scale = 0.1
    targets = made_up_targets(scale)
    folder = tmp_path / "capture"
    folder.mkdir()
    (folder / "targets.json").write_text(json.dumps(targets))
    size = (targets["canvas"]["width"], targets["canvas"]["height"])
    for i, name in enumerate(sorted({f for d in clips.scenes(targets).values()
                                     for f in d["images"].values()})):
        Image.new("RGB", size, (40 * i % 256, 90, 160)).save(folder / name)
    return folder


def needs_ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is needed to render a clip")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_writes_scene_and_video_and_the_same_stills_give_the_same_bytes(small_capture, tmp_path):
    needs_ffmpeg()
    name = "05-move-between-sections"
    first = clips.build(small_capture, names=[name], width=224)
    assert [v.name for v in first] == [f"{name}.mp4"]
    scene = json.loads((small_capture / "clips" / f"{name}.json").read_text())
    assert all(p.startswith("../") for p in scene["images"].values())
    once = digest(first[0])
    again = clips.build(small_capture, names=[name], width=224)  # replaces its own output
    assert digest(again[0]) == once


def test_guide_copy_replaces_clips_and_removes_stale_ones_only(small_capture, tmp_path):
    needs_ffmpeg()
    guide = tmp_path / "guide"
    guide.mkdir()
    (guide / "00-old-clip.mp4").write_bytes(b"old")
    (guide / "notes.txt").write_text("kept")
    made = clips.build(small_capture, names=["05-move-between-sections"], width=224,
                       guide=True, guide_dir=guide)
    assert sorted(p.name for p in guide.iterdir()) == ["05-move-between-sections.mp4", "notes.txt"]
    assert digest(guide / made[0].name) == digest(made[0])

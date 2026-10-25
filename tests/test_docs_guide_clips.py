"""The User Guide's four short clips from guide_clips.py: their step lists,
drafted from made-up targets, their posters and videos, and their place in
the guide.
"""

import importlib.util
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from tests.test_docs_capture import capture  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parents[1]
CAPTURE_DIR = REPO / "dev" / "docs_media" / "capture"
TOOL = REPO / "dev" / "docs_media" / "walkthrough" / "walkthrough.py"
GUIDE = REPO / "docs" / "USER_GUIDE.md"
GUIDE_IMAGES = REPO / "docs" / "assets" / "images" / "user-guide"
GUIDE_VIDEOS = REPO / "docs" / "assets" / "videos" / "user-guide"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def clips():
    return load("docs_guide_clips", CAPTURE_DIR / "guide_clips.py")


@pytest.fixture(scope="module")
def tool():
    return load("docs_walkthrough", TOOL)


def made_up_targets():
    """Targets shaped like a real run's, on a 2560 x 1440 frame."""
    loop = [[round(760 + 140 * math.cos(t / 24 * math.pi)), round(700 + 104 * math.sin(t / 24 * math.pi))]
            for t in range(49)]
    loop[-1] = loop[0]
    return {
        "file_menu": {"center": [48, 18]},
        "open_series_row": {"center": [244, 98]},
        "lists_menu": {"center": [410, 18]},
        "object_list_row": {"center": [560, 64]},
        "object_list_close": {"center": [22, 84]},
        "next_section_button": {"center": [2440, 1240]},
        "previous_section_button": {"center": [2440, 1340]},
        "closed_trace_button": {"center": [2500, 470]},
        "draw_path": {"points": loop, "color": [255, 128, 64]},
    }


@pytest.fixture(scope="module")
def scenes(clips, tool):
    return {name: tool.draft(steps) for name, steps in clips.steps_files(made_up_targets()).items()}


@pytest.fixture
def scene(clips, tool, scenes, tmp_path):
    """The drafted scene of one clip, loaded the way the renderer loads it."""
    for file in clips.FRAMES.values():
        Image.new("RGB", clips.FRAME_SIZE, (90, 90, 90)).save(tmp_path / file)
    folder = tmp_path / "clip"
    folder.mkdir()

    def load_scene(name):
        path = folder / f"{name}.json"
        path.write_text(json.dumps(scenes[name]))
        return tool.Scene(path)
    return load_scene


# where each clip's clicks land, in order; "path start" is the press that
# starts the drag
CLICK_TARGETS = {
    "04-open-series": ["file_menu", "open_series_row"],
    "05-move-between-sections": ["next_section_button", "previous_section_button"],
    "06-draw-closed-trace": ["closed_trace_button", "path start"],
    "09-open-object-list": ["lists_menu", "object_list_row", "object_list_close"],
}


def test_there_are_four_clips_of_4_to_9_seconds(scenes):
    assert set(scenes) == set(CLICK_TARGETS)
    for name, data in scenes.items():
        assert 4 <= data["duration"] <= 9, (name, data["duration"])


def test_every_click_lands_on_its_target(scenes, scene):
    targets = made_up_targets()
    for name in scenes:
        sc = scene(name)
        expected = [targets["draw_path"]["points"][0] if key == "path start"
                    else targets[key]["center"] for key in CLICK_TARGETS[name]]
        assert len(sc.clicks) == len(expected), name
        for when, (ex, ey) in zip(sc.clicks, expected):
            x, y = sc.cursor_at(when)
            assert math.hypot(x - ex, y - ey) < 0.5, name


def test_the_camera_never_moves(scenes, scene):
    # the frames are already 2560 x 1440, so any zoom or pan would scale them
    for name in scenes:
        sc = scene(name)
        for i in range(int(sc.duration * 10)):
            assert sc.camera_at(i / 10) == (1280, 720, 1), name


def test_every_clip_ends_on_its_first_screen_with_no_pointer(scenes, scene):
    for name in scenes:
        sc = scene(name)
        assert sc.state_at(sc.duration)[0] == sc.states[0]["image"], name
        last = sc.states[-1]
        assert last["time"] + last.get("fade", 0) < sc.duration, name
        # the pointer fades in from nothing and is gone before the loop
        assert sc.cursor_opacity(0) == 0, name
        assert sc.cursor_opacity(sc.duration) == 0, name


def test_every_screen_a_clip_shows_is_a_frame_the_script_shoots(clips, scenes):
    for name, data in scenes.items():
        for image in data["images"].values():
            assert image.removeprefix("../") in clips.FRAMES.values(), (name, image)
        for state in data["states"]:
            assert state["image"] in data["images"], (name, state)


def test_a_drawn_trace_cuts_to_its_plain_look_before_the_selection_fades_in(scenes):
    data = scenes["06-draw-closed-trace"]
    drag = next(m for m in data["moves"] if "stroke" in m)
    by_image = {s["image"]: s for s in data["states"]}
    plain, drawn = by_image["drawn-plain"], by_image["drawn"]
    # the live stroke gives way to the unselected trace, drawn the same way...
    assert drag["stroke"]["until"] <= plain["time"] < drag["stroke"]["until"] + 0.1
    assert plain.get("fade", 0) == 0
    # ...and only then does the selected look fade in
    assert drawn["time"] > plain["time"]
    assert drawn["fade"] >= 0.2


def test_the_live_stroke_has_the_traces_color_and_one_point_width(scenes):
    stroke = next(m for m in scenes["06-draw-closed-trace"]["moves"] if "stroke" in m)["stroke"]
    assert stroke["color"] == [255, 128, 64]
    assert stroke["width"] == 2


def test_a_menu_row_lights_up_when_the_pointer_reaches_it(scenes, scene):
    targets = made_up_targets()
    for name, row in (("04-open-series", "open_series_row"), ("09-open-object-list", "object_list_row")):
        sc = scene(name)
        hovered = next(s for s in sc.states if s["image"].endswith("-row"))
        x, y = sc.cursor_at(hovered["time"])
        cx, cy = targets[row]["center"]
        assert math.hypot(x - cx, y - cy) < 30, name


# --- the guide --------------------------------------------------------------


def figures():
    return re.findall(r'<figure class="clip" markdown>(.*?)</figure>', GUIDE.read_text(), re.S)


def test_the_guide_embeds_each_clip_with_its_poster_size_and_length(clips, scenes):
    # each clip is its poster image and a link to its MP4, which
    # docs/javascripts/clips.js turns into the looping video
    found = {}
    for figure in figures():
        link = re.search(r"\[▶ (\d+) s · loops\]\(assets/videos/user-guide/([^)]+)\.mp4\)"
                         r"\{ \.clip-src \}", figure)
        assert link, figure
        found[link.group(2)] = (int(link.group(1)), figure)
    assert set(found) == set(scenes)
    for name, (seconds, figure) in found.items():
        poster = re.search(r"!\[([^\]]+)\]\(assets/images/user-guide/([^)]+)\)(\{[^}]*\})", figure)
        assert poster.group(2) == clips.poster(name), name
        assert poster.group(1).startswith("Clip: "), name
        assert poster.group(3) == '{ data-width="1280" data-height="720" }', name
        assert seconds == round(scenes[name]["duration"]), name
        assert "<figcaption markdown>**" in figure, name


def test_each_poster_is_a_2x_still_the_still_script_leaves_alone(clips, scenes, capture):  # noqa: F811
    for name in scenes:
        path = GUIDE_IMAGES / clips.poster(name)
        with Image.open(path) as image:
            assert image.size == clips.FRAME_SIZE, name
        assert path.name in capture.NOT_CAPTURED, name


def test_each_clip_is_2560_by_1440_and_as_long_as_its_tag(scenes):
    if not shutil.which("ffprobe"):
        pytest.skip("FFprobe is needed to read the clips")
    for name, data in scenes.items():
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json",
             str(GUIDE_VIDEOS / f"{name}.mp4")], check=True, capture_output=True, text=True)
        info = json.loads(probe.stdout)
        stream = info["streams"][0]
        assert (stream["width"], stream["height"]) == (2560, 1440), name
        assert round(float(info["format"]["duration"])) == round(data["duration"]), name


def test_a_guide_copy_writes_each_video_and_its_poster_only(clips, tmp_path):
    out, videos, images = tmp_path / "out", tmp_path / "videos", tmp_path / "images"
    for folder in (out, videos, images):
        folder.mkdir()
    for key, file in clips.FRAMES.items():
        (out / file).write_bytes(key.encode())
    made = []
    for name in CLICK_TARGETS:
        (out / name).mkdir()
        made.append(out / name / f"{name}.mp4")
        made[-1].write_bytes(f"video {name}".encode())
    (videos / "11-add-to-scene.mp4").write_bytes(b"made by walkthrough_3d.py")

    clips.copy_to_guide(out, made, made_up_targets(), videos, images)

    assert (videos / "11-add-to-scene.mp4").read_bytes() == b"made by walkthrough_3d.py"
    for name in CLICK_TARGETS:
        assert (videos / f"{name}.mp4").read_bytes() == f"video {name}".encode()
    assert (images / "04-open-series-start.png").read_bytes() == b"welcome"
    for name in ("05-move-between-sections", "06-draw-closed-trace", "09-open-object-list"):
        assert (images / clips.poster(name)).read_bytes() == b"open"
    assert len(list(images.iterdir())) == 4

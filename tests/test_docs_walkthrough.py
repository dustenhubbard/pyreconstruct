"""The User Guide's section 11 clip: the made-up series neurites.py writes, the
step list walkthrough_3d.py fills in, and the clip's place in the guide.
"""

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from tests.test_docs_capture import capture  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parents[1]
CAPTURE_DIR = REPO / "dev" / "docs_media" / "capture"
GUIDE = REPO / "docs" / "USER_GUIDE.md"
CLIP = REPO / "docs" / "assets" / "videos" / "user-guide" / "11-add-to-scene.mp4"
POSTER = REPO / "docs" / "assets" / "images" / "user-guide" / "11-add-to-scene-start.png"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, CAPTURE_DIR / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def neurites():
    return load("docs_neurites", "neurites.py")


@pytest.fixture(scope="module")
def walkthrough():
    return load("docs_walkthrough_3d", "walkthrough_3d.py")


# --- the series -------------------------------------------------------------


def test_the_series_holds_the_four_objects_the_clip_selects(neurites, walkthrough, tmp_path):
    data = json.loads(neurites.write_series(tmp_path, images=False).read_text())
    names = {name for section in data["sections"] for name in section["contours"]}
    assert sorted(names) == walkthrough.OBJECTS
    assert len(data["sections"]) == neurites.SECTIONS


def test_every_trace_is_a_closed_outline(neurites, tmp_path):
    data = json.loads(neurites.write_series(tmp_path, images=False).read_text())
    for section in data["sections"]:
        for name, rows in section["contours"].items():
            for x, y, _color, closed, negative, *_ in rows:
                assert closed and not negative, name
                assert len(x) == len(y) >= 3, name


def test_the_spine_is_one_outline_on_every_section_it_crosses(neurites):
    crossed = [k for k in range(neurites.SECTIONS) if "d01sp01" in neurites.shapes(k)]
    assert crossed == list(range(14, 27))
    for k in crossed:
        assert len(neurites.shapes(k)["d01sp01"]) == 1, k


def test_the_series_is_the_same_on_every_run(neurites, tmp_path):
    first = neurites.write_series(tmp_path / "a", images=False).read_bytes()
    second = neurites.write_series(tmp_path / "b", images=False).read_bytes()
    assert first == second


# --- the step list ----------------------------------------------------------


def test_every_step_shows_a_frame_the_script_shoots(walkthrough):
    steps = json.loads(walkthrough.STEPS_TEMPLATE.read_text())
    images = set(walkthrough.FRAMES)
    for step in steps["steps"]:
        assert step["image"] in images, step
        assert step.get("after", step["image"]) in images, step


def test_the_camera_never_zooms(walkthrough):
    # the frames are already 2560 x 1440, so any zoom would scale them
    steps = json.loads(walkthrough.STEPS_TEMPLATE.read_text())
    views = [steps["camera_start"], steps["camera_end"]] + [s["camera"] for s in steps["steps"]]
    for view in views:
        assert view == {"x": 1280, "y": 720, "zoom": 1}


# --- the guide --------------------------------------------------------------


def test_the_guide_embeds_the_clip_with_its_poster():
    figures = re.findall(r'<figure class="clip walkthrough" markdown>(.*?)</figure>',
                         GUIDE.read_text(), re.S)
    assert len(figures) == 1
    figure = figures[0]
    assert "](assets/images/user-guide/11-add-to-scene-start.png)" in figure
    assert "[▶ 16 s · loops](assets/videos/user-guide/11-add-to-scene.mp4){ .clip-src }" in figure
    assert "![Clip: " in figure
    assert "<figcaption markdown>**" in figure
    assert CLIP.is_file()


def test_the_poster_is_a_2x_still_the_capture_script_leaves_alone(capture):  # noqa: F811
    with Image.open(POSTER) as poster:
        assert poster.size == (2560, 1440)
    assert POSTER.name in capture.NOT_CAPTURED


def test_the_clip_is_2560_by_1440_and_as_long_as_its_tag():
    if not shutil.which("ffprobe"):
        pytest.skip("FFprobe is needed to read the clip")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(CLIP)],
        check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    assert (stream["width"], stream["height"]) == (2560, 1440)
    assert round(float(info["format"]["duration"])) == 16


def test_each_clip_poster_gives_the_page_its_size():
    # clips.js sizes the video from data-width and data-height, falling back
    # to 1280 x 720, so the page holds the right shape before the poster or
    # the video loads; every poster is a 2x still that names its size
    script = (REPO / "docs" / "javascripts" / "clips.js").read_text()
    assert "Number(poster.dataset.width) || 1280" in script
    assert "Number(poster.dataset.height) || 720" in script
    figures = re.findall(r'<figure class="clip[^"]*" markdown>(.*?)</figure>', GUIDE.read_text(), re.S)
    assert figures
    for figure in figures:
        poster = re.search(r"\]\((assets/images/user-guide/[^)]+)\)(\{[^}]*\})?", figure)
        with Image.open(REPO / "docs" / poster.group(1)) as image:
            width, height = image.size
        attrs = poster.group(2) or ""
        assert f'data-width="{width // 2}"' in attrs, poster.group(1)
        assert f'data-height="{height // 2}"' in attrs, poster.group(1)

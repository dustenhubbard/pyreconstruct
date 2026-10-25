"""The walkthrough renderer, dev/docs_media/walkthrough/walkthrough.py: a short
step list drafted into a timed scene and rendered over made-up stills, with
clicks, key badges, drags, strokes and looping endings.
"""

import importlib.util
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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


def drag_steps(next_fade=None, **drag):
    after = {"image": "c", "point": CORNER[-1], "camera": STILL}
    if next_fade:
        after["fade"] = next_fade
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
            after,
        ],
    }


@pytest.fixture
def drag_scene(tool, tmp_path):
    def make(next_fade=None, **drag):
        names = ("a", "b", "c", "r1", "r2", "r3", "r4")
        for i, name in enumerate(names):
            image = Image.new("RGB", (160, 90), (30 * i, 120, 200 - 20 * i))
            if name == "c":  # the screen after the release holds the drawn line
                ImageDraw.Draw(image).line(CORNER, fill=tuple(STROKE), width=2)
            image.save(tmp_path / f"{name}.png")
        path = tmp_path / "drag-scene.json"
        path.write_text(json.dumps(tool.draft(drag_steps(next_fade, **drag))))
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


def test_a_stroke_grows_behind_the_pointer_and_gives_way_to_the_next_screen(drag_scene):
    scene = drag_scene(stroke={"color": STROKE, "width": 2})
    drag = the_drag(scene)
    after = next(st for st in scene.states if st["image"] == "c")
    assert drag["stroke"]["until"] == after["time"] > drag["end"]
    mid = (drag["start"] + drag["end"]) / 2
    (stroke, points), = scene.strokes_at(mid)
    assert points[0] == pytest.approx(CORNER[0])
    assert points[-1] == pytest.approx(scene.cursor_at(mid))
    assert scene.strokes_at(drag["start"] - 0.01) == []
    (stroke, points), = scene.strokes_at(drag["end"])
    assert points[-1] == pytest.approx(CORNER[-1])
    assert scene.strokes_at(after["time"]) == []


@pytest.mark.parametrize("next_fade", [None, 0.2])
def test_the_line_never_blinks_away_at_the_release(tool, drag_scene, next_fade):
    scene = drag_scene(next_fade, stroke={"color": STROKE, "width": 2})
    drag = the_drag(scene)
    renderer = tool.Renderer(scene, 160)
    # every frame from just before the release until well after the next
    # screen has shown: the line is there, drawn or captured
    first, last = round((drag["end"] - 0.1) * scene.fps), round((drag["end"] + 0.5) * scene.fps)
    for i in range(first, last):
        r, g, b = (int(v) for v in renderer.frame(i / scene.fps)[20, 30])
        assert r > 215 and g < 60 and b > 215, (i / scene.fps, (r, g, b))


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


def test_a_loop_whose_camera_moves_ends_on_its_opening_frame(tool, tmp_path):
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60))):
        image = Image.new("RGB", (160, 90), color)
        ImageDraw.Draw(image).rectangle((30, 30, 60, 50), fill=(250, 250, 250))  # detail to line up
        image.save(tmp_path / f"{name}.png")
    path = tmp_path / "moving.json"
    # no fixed camera: the view follows the targets, zoomed in
    path.write_text(json.dumps(tool.draft({
        "size": [160, 90], "images": {"a": "a.png", "b": "b.png"}, "loop": True,
        "steps": [{"image": "a", "click": [20, 20]}, {"image": "b", "click": [140, 70]}]})))
    scene = tool.Scene(path)
    assert scene.camera_at(scene.duration) == scene.camera_at(0)
    assert len({scene.camera_at(i / 10) for i in range(int(scene.duration * 10))}) > 1
    renderer = tool.Renderer(scene, 160)
    first = renderer.frame(0).astype(int)
    last = renderer.frame((tool.frame_count(scene) - 1) / scene.fps).astype(int)
    assert abs(first - last).max() <= 2


def run_late(kind, spec):
    """Make one kind of timed element in `spec` run on past the last step."""
    if kind == "screen fade":
        spec["steps"][-1]["after_fade"] = 2.0
    elif kind == "key badge":
        spec["timing"]["key_hold"] = 3
    elif kind == "click ring":
        spec["style"] = {"ring_duration": 3}
    elif kind == "pointer fade":
        spec["style"] = {"cursor_fade": 3}
    elif kind == "camera move":  # a camera that follows the pointer, slow to return
        for step in spec["steps"]:
            del step["camera"]
        del spec["camera_start"], spec["camera_end"]
        spec["timing"]["outro"] = 3
    return spec


@pytest.mark.parametrize("back_to", ["a", "c"])
@pytest.mark.parametrize("kind", ["screen fade", "key badge", "click ring", "pointer fade",
                                  "camera move"])
def test_a_loop_ends_on_its_opening_frame_after_everything_has_finished(tool, tmp_path, kind,
                                                                         back_to):
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60)), ("c", (60, 60, 200))):
        image = Image.new("RGB", (160, 90), color)
        ImageDraw.Draw(image).rectangle((30, 30, 60, 50), fill=(250, 250, 250))
        image.save(tmp_path / f"{name}.png")
    spec = steps()
    spec["steps"][-1]["after"] = back_to
    spec.update(loop=True, timing={"outro": 0.2, "tail": 0.3})
    path = tmp_path / "late.json"
    path.write_text(json.dumps(tool.draft(run_late(kind, spec))))
    scene = tool.Scene(path)
    # no fade is cut short: each screen starts only once the one before has
    # fully shown
    for before, after in zip(scene.states, scene.states[1:]):
        assert after["time"] >= before["time"] + before.get("fade", 0), after
    renderer = tool.Renderer(scene, 160)
    first = renderer.frame(0).astype(int)
    last = renderer.frame((tool.frame_count(scene) - 1) / scene.fps).astype(int)
    assert abs(first - last).max() <= 2


@pytest.mark.parametrize("kind", ["screen fade", "typing", "pointer move", "stroke", "click ring",
                                  "key badge", "camera", "pointer fade"])
def test_settled_counts_every_timed_element(tool, kind):
    # each kind in turn ends last, at 9 s; everything else ends by 1 s
    late = {
        "screen fade": {"states": [{"time": 0, "image": "a"}, {"time": 7, "image": "b", "fade": 2}]},
        "typing": {"states": [{"time": 0, "image": "a"},
                              {"time": 6, "image": "b", "type": {"box": [0, 0, 1, 1], "duration": 3}}]},
        "pointer move": {"moves": [{"start": 8, "end": 9, "to": [1, 1]}]},
        "stroke": {"moves": [{"start": 0, "end": 1, "path": [[0, 0], [1, 1]],
                              "stroke": {"color": [0, 0, 0], "width": 2, "until": 9}}]},
        "click ring": {"clicks": [9 - tool.STYLE["ring_duration"]]},
        "key badge": {"keys": [{"start": 8, "end": 9, "text": "A"}]},
        "camera": {"camera": [{"time": 0, "x": 0, "y": 0, "zoom": 1}, {"time": 9, "x": 0, "y": 0, "zoom": 1}]},
        "pointer fade": {"cursor_fade_out": 9 - tool.STYLE["cursor_fade"]},
    }[kind]
    scene = {"states": [{"time": 0, "image": "a"}], "moves": [], "clicks": [0.5], "keys": [],
             "camera": [{"time": 0, "x": 0, "y": 0, "zoom": 1}], "cursor_fade_out": 0.5, **late}
    assert tool.settled(scene, tool.STYLE) == pytest.approx(9)


def stills(tmp_path, size=(160, 90)):
    """Three plain stills, each with a light block, so any offset shows."""
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60)), ("c", (60, 60, 200))):
        image = Image.new("RGB", size, color)
        ImageDraw.Draw(image).rectangle((30, 30, 60, 50), fill=(250, 250, 250))
        image.save(tmp_path / f"{name}.png")


def last_frame_time(tool, scene):
    return (tool.frame_count(scene) - 1) / scene.fps


TINY = 1e-6  # opacities and times this close to their limit show nothing


def assert_clean(scene, t):
    """Nothing but the screen and the camera shows at `t`."""
    assert all(a < TINY for _, a in scene.keys_at(t)), "a key badge"
    assert scene.strokes_at(t) == [], "a stroke"
    assert not any(-TINY < t - c < scene.style["ring_duration"] - TINY for c in scene.clicks), "a click ring"
    assert scene.cursor_opacity(t) < TINY, "the pointer"


def assert_loops_cleanly(tool, scene):
    """The first and last frames match, and nothing is under way in either."""
    last = last_frame_time(tool, scene)
    assert_clean(scene, 0)
    assert_clean(scene, last)
    image, previous, mix = scene.state_at(last)
    assert image == scene.states[0]["image"], "the last screen"
    assert previous is None or mix > 1 - TINY, "a screen fade"
    assert scene.camera_at(last) == pytest.approx(scene.camera_at(0)), "the camera"
    renderer = tool.Renderer(scene, scene.size[0])
    first = renderer.frame(0).astype(int)
    assert abs(first - renderer.frame(last).astype(int)).max() <= 2


@pytest.mark.parametrize("kind", ["key badge", "stroke"])
def test_a_loop_with_no_tail_ends_after_everything_has_finished(tool, tmp_path, kind):
    # each ends exactly on the 0.1 s grid that durations are rounded to
    stills(tmp_path)
    if kind == "key badge":
        last = {"image": "b", "click": [140, 70], "camera": STILL, "keys": "Right-click", "after": "a"}
        timing = {"tail": 0, "key_hold": 2.04}
    else:
        last = {"image": "b", "drag": [[30, 30], [130, 30], [130, 70]], "camera": STILL,
                "stroke": {"color": STROKE, "width": 2}, "after": "a", "after_fade": 1.93}
        timing = {"tail": 0}
    spec = {"size": [160, 90], "images": {"a": "a.png", "b": "b.png", "c": "c.png"},
            "camera_start": STILL, "camera_end": STILL, "loop": True, "timing": timing,
            "steps": [{"image": "a", "click": [20, 20], "camera": STILL}, last]}
    path = tmp_path / "no-tail.json"
    path.write_text(json.dumps(tool.draft(spec)))
    assert_loops_cleanly(tool, tool.Scene(path))


@pytest.mark.parametrize("kind", ["key badge", "click ring", "screen change"])
def test_a_loop_opens_on_its_first_screen_with_nothing_over_it(tool, tmp_path, kind):
    # each would start at or before the first frame without the loop's lead
    stills(tmp_path)
    first = {"image": "a", "click": [20, 20], "camera": STILL}
    second = {"image": "b", "click": [140, 70], "camera": STILL, "after": "a"}
    if kind == "key badge":
        first.update(keys="A", move=0.1)
        timing = {"intro": 0.1}
    elif kind == "click ring":  # a click that changes nothing on screen
        first["move"] = 0
        second.update(image="a", after="b")
        timing = {"intro": 0, "settle": 0}
    else:  # a point with no move and no wait: the next screen comes at once
        del first["click"]
        first.update(point=[20, 20], move=0)
        timing = {"intro": 0}
    spec = {"size": [160, 90], "images": {"a": "a.png", "b": "b.png", "c": "c.png"},
            "camera_start": STILL, "camera_end": STILL, "loop": True, "timing": timing,
            "steps": [first, second]}
    path = tmp_path / "opening.json"
    path.write_text(json.dumps(tool.draft(spec)))
    assert_loops_cleanly(tool, tool.Scene(path))


def random_loop(seed):
    """A drafted loop scene made from `seed`: any mix of steps and timings."""
    rng = random.Random(seed)

    def at():
        return [rng.randint(5, 155), rng.randint(5, 85)]

    steps = []
    for _ in range(rng.randint(1, 4)):
        step = {"image": rng.choice("abc")}
        kind = rng.choice(["click", "point", "drag"])
        if kind == "drag":
            path = [at() for _ in range(rng.randint(2, 4))]
            path.append([path[0][0] + 7, path[0][1] + 3])  # some length, always
            step.update(drag=path, drag_time=rng.choice([0.5, 1.0, 2.0]))
            if rng.random() < 0.5:
                step["stroke"] = {"color": [255, 0, 255], "width": 2}
            if rng.random() < 0.3:
                step["frames"] = rng.sample(["a", "b", "c"], rng.randint(1, 3))
        else:
            step[kind] = at()
        if rng.random() < 0.4:
            step["fade"] = rng.choice([True, 0.3, 1.0])
        if rng.random() < 0.4:
            step["keys"] = rng.choice(["⇧ Shift", "Right-click", "A"])
        if rng.random() < 0.5:
            step["camera"] = STILL
        else:
            step["zoom"] = rng.choice([1, 1.5, 2])
        steps.append(step)
    # the opening: an early first move, or none, and a badge on the first step
    steps[0]["move"] = rng.choice([0, 0.1, 1.6])
    if rng.random() < 0.4:
        steps[0]["keys"] = "A"
    if rng.random() < 0.7:
        steps[-1]["after"] = rng.choice("abc")
        if rng.random() < 0.5:
            steps[-1]["after_fade"] = rng.choice([0.2, 1.0, 1.93])
    return {
        "size": [160, 90], "images": {"a": "a.png", "b": "b.png", "c": "c.png"}, "steps": steps,
        "loop": rng.choice([True, 0.3, 1.5]),
        "timing": {"tail": rng.choice([0, 0, 0.1, 0.3]), "outro": rng.choice([0, 0.1, 0.5, 1.65]),
                   "intro": rng.choice([0, 0.1, 0.7]), "settle": rng.choice([0, 0.2]),
                   "outro_delay": rng.choice([0, 0.37]), "key_hold": rng.choice([0.5, 2.04, 3])},
        "style": {"cursor_fade": rng.choice([0.2, 0.4, 3]), "fps": rng.choice([10, 30, 60]),
                  "ring_duration": rng.choice([0.45, 2])},
    }


def test_random_drafted_loops_end_on_their_opening_frame(tool, tmp_path):
    stills(tmp_path)
    for seed in range(64):
        path = tmp_path / f"random-{seed}.json"
        path.write_text(json.dumps(tool.draft(random_loop(seed))))
        try:
            assert_loops_cleanly(tool, tool.Scene(path))
        except AssertionError as error:
            raise AssertionError(f"seed {seed}: {random_loop(seed)}") from error


def test_a_loop_waits_for_a_slower_pointer_fade(tool, tmp_path):
    for name, color in (("a", (200, 60, 60)), ("b", (60, 200, 60)), ("c", (60, 60, 200))):
        Image.new("RGB", (160, 90), color).save(tmp_path / f"{name}.png")
    path = tmp_path / "slow.json"
    spec = {**steps(), "loop": True, "style": {"cursor_fade": 3},
            "timing": {"outro": 0.2, "tail": 0.3}}
    path.write_text(json.dumps(tool.draft(spec)))
    scene = tool.Scene(path)
    last = scene.states[-1]
    assert last["image"] == "a"
    assert last["time"] >= scene.cursor_fade_out + 3
    assert last["time"] + last["fade"] < scene.duration
    assert scene.cursor_opacity(scene.duration) == 0


def test_a_looping_clip_that_ends_where_it_began_adds_no_fade(tool, scene_file, tmp_path):
    spec = steps()
    spec["steps"][-1]["after"] = "a"
    path = tmp_path / "back.json"
    # a short ending, which a loop must stretch until the pointer has gone
    timing = {"outro": 0.2, "tail": 0.3}
    path.write_text(json.dumps(tool.draft({**spec, "loop": True, "timing": timing})))
    scene = tool.Scene(path)
    assert [s["image"] for s in scene.states] == ["a", "b", "a"]
    # and the pointer is gone before the loop starts again
    assert scene.cursor_opacity(scene.duration) == 0

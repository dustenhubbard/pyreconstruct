"""The staged DMG instructions must name the app shipped beside them."""

import base64
from collections import Counter
import html
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("flavor,app_name,icon", [
    ("dev", "PyReconstruct Dev", "PyReconstructDev.png"),
    ("stable", "PyReconstruct", "PyReconstruct.png"),
])
def test_dmg_stages_flavor_specific_first_launch_help(tmp_path, flavor, app_name, icon):
    packaging = tmp_path / "packaging"
    shutil.copytree(ROOT / "packaging" / "macos", packaging / "macos")
    img = tmp_path / "PyReconstruct" / "assets" / "img"
    img.mkdir(parents=True)
    for name in ("PyReconstruct.png", "PyReconstructDev.png"):
        shutil.copyfile(ROOT / "PyReconstruct" / "assets" / "img" / name, img / name)
    if flavor == "dev":
        (packaging / "FLAVOR").write_text("dev\n")
    (tmp_path / "dist" / f"{app_name}.app").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Exercise the real staging script; replace only the disk-image builder.
    _fake_dmgbuild(bin_dir)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0.dev20260927", ARCH="arm64", TMPDIR=str(tmp_path))
    subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                   env=env, check=True, capture_output=True, text=True)
    call = json.loads((tmp_path / "dmgbuild-call.json").read_text())
    # The volume (the window title) carries no version; the file name keeps
    # the shape the in-app updater parses.
    suffix = "-Dev" if flavor == "dev" else ""
    assert call["volume"] == app_name
    assert call["out"] == f"PyReconstruct-1.24.0.dev20260927-macOS-arm64{suffix}.dmg"
    assert call["defines"]["app"] == f"dist/{app_name}.app"
    assert Path(call["defines"]["guide"]).name == "Read Before First Launch.html"
    shutil.copyfile(call["defines"]["guide"], tmp_path / "staged-guide.html")
    page = (tmp_path / "staged-guide.html").read_text()
    # The guide carries the icon of the app in this image, as one offline file.
    icon_data = base64.b64encode((img / icon).read_bytes()).decode("ascii")
    assert f'url("data:image/png;base64,{icon_data}")' in page
    text = page.replace(icon_data, "")
    # Each image gets its own macOS 27 screenshots, not the other app's.
    for n in (1, 2, 3, 4):
        shot = base64.b64encode(
            (ROOT / "packaging" / "macos" / "first-launch" / f"{flavor}-{n}.png").read_bytes()
        ).decode("ascii")
        assert f'src="data:image/png;base64,{shot}"' in text
        text = text.replace(shot, "")
    assert f"<title>Open {app_name} for the first time</title>" in text
    assert "@" not in re.sub(r"<script>.*</script>", "", text, flags=re.S).replace("@media", "")
    assert "PyReconstruct" not in text.replace(app_name, "")
    assert "System Settings" not in text
    assert "Hold Command and press the space bar" in text
    command = html.unescape(re.search(r'<code class="cmd" id="cmd">(.*?)</code>', text).group(1))
    assert shlex.split(command) == [
        "xattr", "-dr", "com.apple.quarantine", f"/Applications/{app_name}.app"
    ]
    assert "no message means it worked" in text
    # The steps stay in order, and both recovery cases are covered.
    order = [text.index(h) for h in ("Copy the app", "Run one command in Terminal", "Open the app<")]
    assert order == sorted(order)
    assert "No such file or directory" in text and "Force Quit" in text
    assert "click Done. Do not click Move to Trash" in text


def test_dmg_leaves_out_first_launch_help_for_a_signed_app(tmp_path):
    packaging = tmp_path / "packaging"
    shutil.copytree(ROOT / "packaging" / "macos", packaging / "macos")
    (packaging / "FLAVOR").write_text("dev\n")
    (tmp_path / "dist" / "PyReconstruct Dev.app").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A Developer ID signature, as codesign -dvv reports it on stderr.
    codesign = bin_dir / "codesign"
    codesign.write_text("#!/bin/sh\n"
                        "echo 'Authority=Developer ID Application: Test (ABCDE12345)' >&2\n")
    codesign.chmod(0o755)
    _fake_dmgbuild(bin_dir)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0.dev20260927", ARCH="arm64", TMPDIR=str(tmp_path))
    result = subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "leaving out the first-launch guide" in result.stdout
    call = json.loads((tmp_path / "dmgbuild-call.json").read_text())
    assert call["volume"] == "PyReconstruct Dev"
    assert call["out"] == "PyReconstruct-1.24.0.dev20260927-macOS-arm64-Dev.dmg"
    assert "guide" not in call["defines"]


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("dmgbuild"),
                    reason="needs macOS, hdiutil and dmgbuild on PATH")
@pytest.mark.parametrize("unreadable,error", [
    (None, None),
    ("Frameworks/lib.dylib", "does not match"),
    ("Frameworks", "could not list"),   # its contents are unknown, so no listing is complete
])
def test_dmg_build_fails_when_the_app_copy_into_the_image_fails(tmp_path, unreadable, error):
    # The real dmgbuild and hdiutil: dmgbuild copies the app with ditto and
    # ignores its exit status, so make_dmg.sh must catch a short copy itself.
    packaging = tmp_path / "packaging"
    shutil.copytree(ROOT / "packaging" / "macos", packaging / "macos")
    img = tmp_path / "PyReconstruct" / "assets" / "img"
    img.mkdir(parents=True)
    shutil.copyfile(ROOT / "PyReconstruct" / "assets" / "img" / "PyReconstruct.png",
                    img / "PyReconstruct.png")
    contents = tmp_path / "dist" / "PyReconstruct.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "PyReconstruct").write_text("#!/bin/sh\n")
    (contents / "Frameworks").mkdir()
    (contents / "Resources").symlink_to("Frameworks")
    lib = contents / "Frameworks" / "lib.dylib"
    lib.write_bytes(b"x" * 4096)
    if unreadable:
        # ditto cannot read it, so the app in the image lacks it.
        (contents / unreadable).chmod(0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Retry at once, and leave other disk images on this machine alone.
    for name in ("sleep", "killall"):
        (bin_dir / name).write_text("#!/bin/sh\n")
        (bin_dir / name).chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0", ARCH="arm64", TMPDIR=str(tmp_path))
    try:
        result = subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                                env=env, capture_output=True, text=True, timeout=600)
    finally:
        (contents / "Frameworks").chmod(0o755)
        lib.chmod(0o644)
    out = tmp_path / "PyReconstruct-1.24.0-macOS-arm64.dmg"
    if unreadable:
        assert result.returncode != 0
        assert error in result.stderr
        assert not out.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert out.is_file()


@pytest.mark.parametrize("python", ["exit 1", "exit 0"])
def test_dmg_build_fails_when_the_app_cannot_be_listed(tmp_path, python):
    # A listing that fails, or that prints nothing, must not count as a match.
    packaging = tmp_path / "packaging"
    shutil.copytree(ROOT / "packaging" / "macos", packaging / "macos")
    (tmp_path / "dist" / "PyReconstruct.app").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Signed, so make_dmg.sh runs $PYTHON only to list the app.
    codesign = bin_dir / "codesign"
    codesign.write_text("#!/bin/sh\n"
                        "echo 'Authority=Developer ID Application: Test (ABCDE12345)' >&2\n")
    for name, body in (("broken-python", python), ("sleep", ""), ("killall", "")):
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    _fake_dmgbuild(bin_dir)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYTHON=str(bin_dir / "broken-python"),
               PYR_PUBLIC="1.24.0", ARCH="arm64", TMPDIR=str(tmp_path))
    result = subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "could not list" in result.stderr
    assert not (tmp_path / "PyReconstruct-1.24.0-macOS-arm64.dmg").exists()


def _fake_dmgbuild(bin_dir):
    """Put a dmgbuild on PATH that records its arguments and writes the dmg,
    and an hdiutil that mounts the app the fake dmgbuild copied."""
    dmgbuild = bin_dir / "dmgbuild"
    dmgbuild.write_text(f"#!{sys.executable}\n" + '''
import json
from pathlib import Path
import shutil
import sys
args = sys.argv[1:]
settings = args[args.index("-s") + 1]
defines = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-D")
volume, out = args[-2:]
assert Path(settings).name == "dmg_settings.py" and Path(settings).is_file()
assert Path(defines["app"]).is_dir() and Path(defines["background"]).is_file()
Path("dmgbuild-call.json").write_text(json.dumps(
    {"volume": volume, "out": out, "defines": defines}))
app = Path(defines["app"])
shutil.copytree(app, Path(out + ".contents") / app.name, symlinks=True)
Path(out).touch()
''')
    dmgbuild.chmod(0o755)
    hdiutil = bin_dir / "hdiutil"
    hdiutil.write_text(f"#!{sys.executable}\n" + '''
import shutil
import sys
args = sys.argv[1:]
if args[0] == "attach":
    mount = args[args.index("-mountpoint") + 1]
    shutil.copytree(args[-1] + ".contents", mount, symlinks=True, dirs_exist_ok=True)
''')
    hdiutil.chmod(0o755)


def _window(app_name, guide):
    """Run dmg_settings.py the way dmgbuild does and return its settings."""
    defines = {"app": f"dist/{app_name}.app",
               "background": str(ROOT / "packaging" / "macos" / "dmg-background.png")}
    if guide:
        defines["guide"] = "/tmp/stage/Read Before First Launch.html"
    settings = {"defines": defines}
    source = (ROOT / "packaging" / "macos" / "dmg_settings.py").read_text()
    exec(compile(source, "dmg_settings.py", "exec"), settings, settings)
    return settings


@pytest.mark.parametrize("guide", [False, True])
@pytest.mark.parametrize("app_name", ["PyReconstruct", "PyReconstruct Dev"])
def test_dmg_window_places_every_item_inside_the_background(app_name, guide):
    from PIL import Image

    s = _window(app_name, guide)
    names = [Path(f).name for f in s["files"]] + list(s["symlinks"])
    assert sorted(s["icon_locations"]) == sorted(names)
    assert s["symlinks"] == {"Applications": "/Applications"}
    assert s["format"] == "UDZO"
    assert not (s["show_toolbar"] or s["show_sidebar"])
    # The app and Applications share a row, the chevron centered between them.
    app = s["icon_locations"][f"{app_name}.app"]
    apps = s["icon_locations"]["Applications"]
    assert app[1] == apps[1]
    one = Image.open(ROOT / "packaging" / "macos" / "dmg-background.png")
    two = Image.open(ROOT / "packaging" / "macos" / "dmg-background@2x.png")
    assert two.size == (one.size[0] * 2, one.size[1] * 2)
    half = s["icon_size"] / 2
    # On the icons' center line, the only dark pixels are the chevron's tip,
    # and it sits in the middle of the gap.
    paper = sum(one.getpixel((10, 10)))
    gap = range(int(app[0] + half), int(apps[0] - half))
    dark = [x for x in gap if sum(one.getpixel((x, app[1]))) < paper / 2]
    assert dark and abs((dark[0] + dark[-1]) / 2 - (app[0] + apps[0]) / 2) < 30
    # The background covers the whole window. Every icon and its label (up to
    # two lines) clear the title bar and Finder's path and status bars, about
    # 90 points together, with room to spare, so the window never scrolls.
    (_, _), (width, height) = s["window_rect"]
    assert one.size[0] >= width and one.size[1] >= height
    for x, y in s["icon_locations"].values():
        assert half <= x <= width - half
        assert y + half + 2 * s["text_size"] * 1.5 <= height - 120


@pytest.mark.parametrize("app_name", ["PyReconstruct", "PyReconstruct Dev"])
def test_dmg_window_matches_the_reference_layout(app_name):
    # Measured from a Finder capture of a reference drag-to-install window:
    # 160 point icons centered 180 and 480 points from the left, a 22 x 40
    # point chevron in (47, 47, 48) between them, on (241, 241, 246).
    from PIL import Image

    s = _window(app_name, guide=False)
    assert s["window_rect"][1] == (660, 422)
    assert s["icon_size"] == 160
    for name, x in ((f"{app_name}.app", 180), ("Applications", 480)):
        assert abs(s["icon_locations"][name][0] - x) <= 1
        assert abs(s["icon_locations"][name][1] - 170) <= 1
    two = Image.open(ROOT / "packaging" / "macos" / "dmg-background@2x.png").convert("RGB")
    assert two.getpixel((10, 10)) == (241, 241, 246)
    dark = [(x, y) for x in range(560, 760) for y in range(240, 480)
            if sum(two.getpixel((x, y))) < 200]
    xs, ys = [x for x, _ in dark], [y for _, y in dark]
    assert abs(min(xs) - 641) <= 1 and abs(max(xs) - 684) <= 1
    assert abs(min(ys) - 321) <= 1 and abs(max(ys) - 401) <= 1
    ink = Counter(two.getpixel(p) for p in dark).most_common(1)[0][0]
    assert ink == (47, 47, 48)

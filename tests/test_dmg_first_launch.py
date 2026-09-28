"""The staged DMG instructions must name the app shipped beside them."""

import base64
import html
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
    # Exercise the real staging script; replace only the disk-image utility.
    hdiutil = bin_dir / "hdiutil"
    hdiutil.write_text(f"#!{sys.executable}\n" + '''
import os
from pathlib import Path
import shutil
import sys
stage = Path(sys.argv[sys.argv.index("-srcfolder") + 1])
assert (stage / (os.environ["EXPECTED_APP"] + ".app")).is_dir()
assert (stage / "Applications").is_symlink()
shutil.copyfile(stage / "Read Before First Launch.html", "staged-guide.html")
Path(sys.argv[-1]).touch()
''')
    hdiutil.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0.dev20260927", ARCH="arm64",
               EXPECTED_APP=app_name, TMPDIR=str(tmp_path))
    subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                   env=env, check=True, capture_output=True, text=True)
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
    hdiutil = bin_dir / "hdiutil"
    hdiutil.write_text(f"#!{sys.executable}\n" + '''
from pathlib import Path
import sys
stage = Path(sys.argv[sys.argv.index("-srcfolder") + 1])
assert (stage / "PyReconstruct Dev.app").is_dir()
assert (stage / "Applications").is_symlink()
assert not (stage / "Read Before First Launch.html").exists()
Path(sys.argv[-1]).touch()
''')
    hdiutil.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0.dev20260927", ARCH="arm64", TMPDIR=str(tmp_path))
    result = subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "leaving out the first-launch guide" in result.stdout

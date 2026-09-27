"""The staged DMG instructions must name the app shipped beside them."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("flavor,app_name", [
    ("dev", "PyReconstruct Dev"),
    ("stable", "PyReconstruct"),
])
def test_dmg_stages_flavor_specific_first_launch_help(tmp_path, flavor, app_name):
    packaging = tmp_path / "packaging"
    shutil.copytree(ROOT / "packaging" / "macos", packaging / "macos")
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
shutil.copyfile(stage / "Read Before First Launch.txt", "staged-readme.txt")
Path(sys.argv[-1]).touch()
''')
    hdiutil.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               PYR_PUBLIC="1.24.0.dev20260927", ARCH="arm64",
               EXPECTED_APP=app_name, TMPDIR=str(tmp_path))
    subprocess.run(["bash", "packaging/macos/make_dmg.sh"], cwd=tmp_path,
                   env=env, check=True, capture_output=True, text=True)
    text = (tmp_path / "staged-readme.txt").read_text()
    assert text.startswith(f"Install and open {app_name}")
    assert "@APP_NAME@" not in text
    assert "PyReconstruct" not in text.replace(app_name, "")
    assert f"Find the message about {app_name} and click Open Anyway." in text
    assert "System Settings" in text
    assert "Privacy & Security" in text
    assert "Terminal" not in text
    assert "xattr" not in text
    assert "sudo" not in text

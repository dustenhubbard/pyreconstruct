"""The macOS legs list the app in their finished dmg for in-place updates.

The dmg is the macOS payload. After the dmg is signed, notarized, and stapled,
the build job attaches it read-only and writes its tree.json from the app
inside (scripts/build_update_payload.py --macos-tree); the release job then
puts both in the manifest. The order and the guards are checked anywhere; the
step's own shell runs against a real dmg on macOS only.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_pruning_preserves_release_tags import workflow_script
from test_update_payload import MANIFEST_SCRIPT, NIGHTLY, STABLE, P, WORKFLOW, _step, _step_order, fake_bundle

ROOT = Path(__file__).resolve().parents[1]
STEP = "List the app in the dmg for in-place updates (macOS)"
STAPLE = "Sign, notarize, and staple the dmg (macOS)"

needs_hdiutil = pytest.mark.skipif(sys.platform != "darwin", reason="attaches a real dmg with hdiutil")


def test_the_tree_is_listed_from_the_finished_dmg_before_the_upload():
    steps = _step_order("build")
    assert steps.index("Build macOS dmg") < steps.index(STAPLE) == steps.index(STEP) - 1
    build = WORKFLOW.read_text(encoding="utf-8").split("\n  build:\n", 1)[1].split("\n  build-linux:\n", 1)[0]
    assert build.index(f"- name: {STEP}\n") < build.index("- uses: actions/upload-artifact@")


def test_a_tag_lists_only_a_signed_app_and_a_failure_keeps_the_dmg():
    step = _step("build", STEP)
    assert ("if: runner.os == 'macOS' && (steps.macsign.outputs.sign == 'true'"
            " || !startsWith(github.ref, 'refs/tags/v'))") in step
    assert "id: macos-tree" in step and "continue-on-error: true" in step
    assert "hdiutil attach -readonly" in step
    upload = WORKFLOW.read_text(encoding="utf-8").split("- uses: actions/upload-artifact@", 1)[1]
    upload = upload.split("\n", 1)[1].split("\n\n", 1)[0]
    assert "steps.macos-tree" not in upload and "path: dist-assets/*" in upload


def _leg(tmp_path, flavor, bundle_flavor=None, arch="arm64"):
    """A macOS leg's working folder after the dmg step: packaging/FLAVOR, scripts, and the dmg."""
    work = tmp_path / "work"
    (work / "packaging").mkdir(parents=True)
    if flavor == "dev":
        (work / "packaging" / "FLAVOR").write_text("dev\n")
    (work / "scripts").symlink_to(ROOT / "scripts")
    version = NIGHTLY if flavor == "dev" else STABLE
    src = tmp_path / "volume"
    src.mkdir()
    fake_bundle(src, bundle_flavor or flavor)
    (work / "dist-assets").mkdir()
    dmg = work / "dist-assets" / P.macos_names(version, flavor, f"macos-{arch}")[0]
    subprocess.run(["hdiutil", "create", "-quiet", "-srcfolder", str(src), "-volname", "PyReconstruct",
                    "-fs", "HFS+", "-format", "UDZO", str(dmg)], check=True, timeout=300)
    return work, version, dmg


def _run_step(work, version, arch="arm64"):
    env = dict(os.environ, PYR_PUBLIC=version, ARCH=arch,
               PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    return subprocess.run(["bash", "-e", "-c", workflow_script(WORKFLOW.name, STEP)], cwd=work, env=env,
                          capture_output=True, text=True, timeout=300)


@needs_hdiutil
@pytest.mark.parametrize("flavor,arch", [("dev", "arm64"), ("stable", "x86_64")])
def test_the_step_lists_the_app_in_the_dmg_and_the_manifest_names_both(tmp_path, flavor, arch):
    work, version, dmg = _leg(tmp_path, flavor, arch=arch)
    r = _run_step(work, version, arch)
    assert r.returncode == 0, r.stdout + r.stderr

    platform = f"macos-{arch}"
    tree_name = P.macos_names(version, flavor, platform)[1]
    assert sorted(p.name for p in (work / "dist-assets").iterdir()) == sorted([dmg.name, tree_name])
    tree = json.loads((work / "dist-assets" / tree_name).read_text())
    assert (tree["platform"], tree["flavor"], tree["bundle_id"]) == (platform, flavor, P.BUNDLE_IDS[flavor])

    dist = tmp_path / "dist"
    shutil.copytree(work / "dist-assets", dist)
    tag = "v" + version
    m = subprocess.run([sys.executable, str(MANIFEST_SCRIPT), str(dist), "--tag", tag, "--flavor", flavor],
                       capture_output=True, text=True, timeout=60)
    assert m.returncode == 0, m.stderr
    entry = json.loads((dist / "update-manifest.json").read_text())["platforms"][platform]
    assert entry["inplace"] == {"enabled": False}
    assert entry["payload"]["name"] == dmg.name and entry["tree"]["name"] == tree_name
    sums = (dist / "SHA256SUMS").read_text()
    assert dmg.name in sums and tree_name in sums


@needs_hdiutil
def test_a_dmg_holding_the_other_flavor_leaves_no_tree_and_keeps_the_dmg(tmp_path):
    work, version, dmg = _leg(tmp_path, "dev", bundle_flavor="stable")
    r = _run_step(work, version)
    assert r.returncode != 0
    assert "::warning::the tree.json did not build" in r.stdout
    assert [p.name for p in (work / "dist-assets").iterdir()] == [dmg.name]

"""The User Guide capture script's safety and output logic.

dev/docs_media/capture/capture.py shoots the guide's screenshots from the real
app on macOS. The shooting needs a Retina screen and an active Cocoa window, so
it is not run here; these tests cover the parts that decide what it refuses and
what it writes: it stops if ROI mode shows, it never points QSettings at the
real settings folder, a source checkout shoots the stable look, --guide
replaces the guide's images and nothing else, and each tool's label carries
its shortcut from the app's own defaults.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dev" / "docs_media" / "capture" / "capture.py"


@pytest.fixture(scope="module")
def capture():
    spec = importlib.util.spec_from_file_location("docs_capture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- ROI mode ---------------------------------------------------------------


def test_stops_when_the_palette_shows_roi_mode(capture):
    names = ["Pointer", "Knife", "Ztool", "ROI mode"]
    with pytest.raises(SystemExit, match="ROI mode"):
        capture.check_no_roi(names)


def test_runs_when_the_palette_has_no_roi_mode(capture):
    capture.check_no_roi(["Pointer", "Knife", "Ztool"])


# --- settings isolation -----------------------------------------------------


def test_refuses_a_settings_file_in_the_real_folder(capture, tmp_path):
    real = tmp_path / "Preferences"
    real.mkdir()
    with pytest.raises(SystemExit, match="refusing to run"):
        capture.check_settings_path(real / "com.khlab.PyReconstruct.plist", real_dir=real)
    with pytest.raises(SystemExit):
        capture.check_settings_path(real, real_dir=real)


def test_refuses_the_real_plist_by_default(capture):
    with pytest.raises(SystemExit):
        capture.check_settings_path(capture.REAL_PLIST)


def test_accepts_a_settings_file_outside_the_real_folder(capture, tmp_path):
    real = tmp_path / "Preferences"
    real.mkdir()
    elsewhere = tmp_path / "isolated" / "KHLab" / "PyReconstruct.ini"
    assert capture.check_settings_path(elsewhere, real_dir=real) == elsewhere.resolve()


@pytest.fixture
def dev_checkout(monkeypatch):
    """A macOS source checkout, which counts as a Dev build; the pin the
    capture sets is undone after the test."""
    from PyReconstruct.modules.constants import build_flavor

    monkeypatch.setattr(build_flavor, "is_dev_build", build_flavor.is_dev_build)
    monkeypatch.setattr(build_flavor, "running_version", lambda: "1.25.0.dev5+g0123abc")
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    monkeypatch.setenv("PYRECON_MAC_UI", "1")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert build_flavor.is_dev_build()
    return build_flavor


def test_isolate_settings_points_the_app_away_from_the_real_folder(
        capture, monkeypatch, dev_checkout):
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")
    monkeypatch.delenv("PYRECON_HYBRID_STORE", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    isolation = capture.isolate_settings()
    assert isolation.installed
    assert "PYRECON_ROI_MODE" not in os.environ
    assert "PYRECON_MAC_UI" not in os.environ
    assert os.environ["PYRECON_HYBRID_STORE"] == "0"
    assert dev_checkout.is_dev_build() is False

    from PySide6.QtCore import QSettings

    for application in ("PyReconstruct", f"PyReconstruct-{capture.SERIES_CODE}"):
        path = Path(QSettings("KHLab", application).fileName()).resolve()
        assert capture.REAL_PREFS.resolve() not in path.parents


def test_a_dev_checkout_shoots_the_stable_look(capture, dev_checkout):
    from PyReconstruct.modules.gui.main import mac_menubar

    capture.pin_stable_build()
    assert dev_checkout.is_dev_build() is False
    assert not mac_menubar.wanted()


# --- --guide ----------------------------------------------------------------


def _frames(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(f"new {name}".encode())
    return [{"file": name} for name in names]


def test_guide_gets_every_shot_but_the_flow_only_frames(capture, tmp_path):
    out, guide = tmp_path / "out", tmp_path / "guide"
    flow_only = sorted(capture.FLOW_ONLY)[0] + ".png"
    shots = _frames(out, ["04-welcome-series.png", flow_only, "13-shortcuts-list.png"])

    kept = capture.copy_to_guide(out, shots, guide)

    assert kept == ["04-welcome-series.png", "13-shortcuts-list.png"]
    assert sorted(p.name for p in guide.iterdir()) == kept
    for name in kept:
        assert (guide / name).read_bytes() == (out / name).read_bytes()


def test_guide_replaces_old_images_and_drops_stale_ones(capture, tmp_path):
    out, guide = tmp_path / "out", tmp_path / "guide"
    guide.mkdir()
    (guide / "04-welcome-series.png").write_bytes(b"old")
    (guide / "99-renamed-away.png").write_bytes(b"stale")
    (guide / "notes.txt").write_text("not an image")
    shots = _frames(out, ["04-welcome-series.png"])

    capture.copy_to_guide(out, shots, guide)

    assert (guide / "04-welcome-series.png").read_bytes() == b"new 04-welcome-series.png"
    assert not (guide / "99-renamed-away.png").exists()
    assert (guide / "notes.txt").read_text() == "not an image"


def test_guide_keeps_the_images_this_script_cannot_shoot(capture, tmp_path):
    out, guide = tmp_path / "out", tmp_path / "guide"
    guide.mkdir()
    for name in capture.NOT_CAPTURED:
        (guide / name).write_bytes(b"by hand")
    shots = _frames(out, ["04-welcome-series.png"])

    capture.copy_to_guide(out, shots, guide)

    for name in capture.NOT_CAPTURED:
        assert (guide / name).read_bytes() == b"by hand"


def test_every_image_not_captured_is_in_the_guide(capture):
    for name in capture.NOT_CAPTURED:
        assert (capture.GUIDE_IMAGES / name).is_file()


# --- tool shortcuts ---------------------------------------------------------


@pytest.mark.parametrize("portable, shown", [
    ("P", "P"),
    ("Shift+K", "Shift+K"),
    ("", ""),
    ("Ctrl+Shift+V", "Cmd+Shift+V (Ctrl+Shift+V on Windows/Linux)"),
    ("Meta+Ctrl+X", "Ctrl+Cmd+X (Meta+Ctrl+X on Windows/Linux)"),
])
def test_shortcut_text_puts_the_macos_form_first(capture, portable, shown):
    assert capture.shortcut_text(portable) == shown


def test_tool_label_names_the_tool_then_its_shortcut(capture):
    assert capture.tool_label("Scissors", "Shift+K") == "Scissors (Shift+K)"
    assert capture.tool_label("Ztool", "") == "Ztool"


def test_every_tool_action_is_a_default_shortcut(capture):
    from PyReconstruct.modules.datatypes.default_settings import default_settings

    for name, action in capture.TOOL_ACTIONS.items():
        assert default_settings.get(action), f"{name}: no default for {action}"


def test_tool_shortcuts_stops_on_a_tool_it_does_not_know(capture):
    with pytest.raises(SystemExit, match="TOOL_ACTIONS"):
        capture.tool_shortcuts(object(), ["A new tool"])

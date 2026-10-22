"""The Mac-native look's fonts and accent (macOS Dev builds only).

Everywhere else the palettes, the scale bar and the field's labels keep
"Courier New" and the selected trace button keeps its yellow frame, so those
builds draw what they drew before. The tests set the platform, the build
flavor and PYRECON_MAC_UI=1 themselves, so they mean the same on every CI
runner; test_mac_ui_hidden.py covers the switch unset.
"""
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QFont, QPalette

from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.palette.buttons import PaletteButton
from PyReconstruct.modules.gui.utils import fonts

PACKAGE = Path(__file__).resolve().parents[1] / "PyReconstruct"

# "Courier New" may appear only in the font helper, in What's New's Windows
# list (now in the helper too), and on the Flag mode button, which the tool
# icon work replaces.
COURIER_ALLOWED = {
    "modules/gui/utils/fonts.py",
    "modules/gui/palette/mouse_palette.py:button.setFont(QFont(\"Courier New\", 25, QFont.Bold))",
}

YELLOW = (255, 255, 0)


@pytest.fixture
def look(monkeypatch):
    """Set the platform and the flavor: look("linux", dev=True) and so on.
    The look is held behind PYRECON_MAC_UI, so the switch is on throughout."""
    monkeypatch.setenv("PYRECON_MAC_UI", "1")

    def set_look(platform, dev):
        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(build_flavor, "is_dev_build", lambda: dev)
    return set_look


@pytest.mark.parametrize("platform, dev", [
    ("linux", True), ("linux", False), ("win32", True), ("win32", False),
    ("darwin", False),
])
def test_other_builds_keep_courier_new(qapp, look, platform, dev):
    look(platform, dev)
    assert not fonts.macLook()
    assert fonts.monoFamily() == "Courier New"
    assert fonts.uiFamily() == "Courier New"
    # the same fonts the call sites built before, attribute for attribute
    assert fonts.monoFont(12) == QFont("Courier New", 12, QFont.Bold)
    assert fonts.uiFont(16) == QFont("Courier New", 16, QFont.Bold)
    assert fonts.uiFont(10, bold=False) == QFont("Courier New", 10)
    assert fonts.uiFont().weight() == QFont.Bold


def test_mac_dev_uses_system_fonts(qapp, look):
    look("darwin", True)
    assert fonts.macLook()
    mono, ui = fonts.monoFamily(), fonts.uiFamily()
    assert mono != "Courier New" and ui != "Courier New"
    assert fonts.monoFont(12).family() == mono
    assert fonts.uiFont(16).family() == ui
    assert fonts.uiFont(16).weight() == QFont.DemiBold


def test_no_hardcoded_courier_new_left():
    found = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel in COURIER_ALLOWED:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "Courier New" in line and f"{rel}:{line.strip()}" not in COURIER_ALLOWED:
                found.append(f"{rel}: {line.strip()}")
    assert found == []


def test_scale_bar_and_field_text_follow_the_helper(qapp, look):
    from PyReconstruct.modules.gui.palette import scale_bar
    look("darwin", True)
    assert scale_bar.outlinedFont(12).family() == fonts.monoFamily()
    look("linux", True)
    assert scale_bar.outlinedFont(12) == QFont("Courier New", 12, QFont.Bold)


def _button(qapp, color=(255, 0, 0)):
    button = PaletteButton(None, None)
    button.setCheckable(True)
    button.resize(40, 40)
    trace = Trace("probe", color, closed=True)
    trace.points = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    button.setTrace(trace)
    button.setChecked(True)
    return button


def _rgb(image, x, y):
    c = QColor(image.pixel(x, y))
    return (c.red(), c.green(), c.blue())


def test_other_builds_keep_the_yellow_frame(qapp, look):
    look("darwin", False)
    button = _button(qapp)
    try:
        image = button.grab().toImage()
        assert _rgb(image, 0, 20) == YELLOW
        assert _rgb(image, 20, 0) == YELLOW
    finally:
        button.deleteLater()


def test_mac_dev_frames_the_selection_in_the_accent(qapp, look):
    look("darwin", True)
    button = _button(qapp, color=(0, 0, 0))
    try:
        for accent in ((10, 96, 255), (230, 40, 160)):
            palette = button.palette()
            palette.setColor(QPalette.Accent, QColor(*accent))
            button.setPalette(palette)  # what a new System Settings accent does
            image = button.grab().toImage()
            ring = _rgb(image, 1, 20)
            assert ring == accent, (ring, accent)
            assert YELLOW not in {_rgb(image, x, y)
                                  for x in range(40) for y in range(40)}
            # the tint behind the trace leans toward the accent but stays light
            tint = _rgb(image, 10, 10)
            assert tint != ring and min(tint) > 120, tint
    finally:
        button.deleteLater()


def test_whats_new_shares_the_family_list():
    from PyReconstruct.modules.gui.dialog import whats_new
    assert whats_new.CODE_FAMILIES is fonts.CODE_FAMILIES

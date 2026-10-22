"""macOS Dev builds draw the mouse palette's tools as Lucide line icons (fork #763).

Each test builds a fresh MousePalette under a chosen platform and build, with
the real gate: `sys.platform` and the version that `build_flavor.is_dev_build`
reads are set, never the gate itself, so taking out either half of
`line_icons.wanted` fails a test here.
"""
import os
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.constants import locations as loc
from PyReconstruct.modules.gui.palette import line_icons
from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette

TOOLS = list(line_icons.TOOL_ICONS)
PNG_TOOLS = ["Pointer", "Pan/Zoom", "Knife", "Scissors", "Closed Trace",
             "Open Trace", "Stamp", "Grid", "Ztool"]


def _build(main_window, monkeypatch, platform, version):
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(build_flavor, "running_version", lambda: version)
    return MousePalette(main_window)


DEV = "1.25.0.dev5+g0123abc"
STABLE = "1.24.0"


def _inked(icon, checked=False, ratio=2.0):
    """The opaque pixels of the icon's 24 pt pixmap at `ratio`."""
    from PySide6.QtGui import QIcon
    state = QIcon.On if checked else QIcon.Off
    img = icon.pixmap(QSize(24, 24), ratio, QIcon.Normal, state).toImage()
    return img, [img.pixelColor(x, y) for x in range(img.width())
                 for y in range(img.height()) if img.pixelColor(x, y).alpha() == 255]


def _same_image(a : QImage, b : QImage) -> bool:
    fmt = QImage.Format_ARGB32
    return a.convertToFormat(fmt) == b.convertToFormat(fmt)


@pytest.mark.gui
def test_mac_dev_gives_every_tool_a_line_icon(main_window, monkeypatch):
    mp = _build(main_window, monkeypatch, "darwin", DEV)
    assert list(mp.mode_buttons) == TOOLS
    for name, (b, _mode, _pos) in mp.mode_buttons.items():
        assert b.text() == "", name
        _img, inked = _inked(b.icon())
        assert inked, name
        assert b.iconSize() == QSize(24, 24)
        assert b.toolTip() == name


@pytest.mark.gui
def test_icons_are_drawn_for_retina(main_window, monkeypatch):
    mp = _build(main_window, monkeypatch, "darwin", DEV)
    img, _inked_px = _inked(mp.mode_buttons["Knife"][0].icon(), ratio=2.0)
    assert (img.width(), img.height()) == (48, 48)
    assert img.devicePixelRatio() == 2.0


@pytest.mark.gui
def test_colors_text_accent_and_flag(main_window, monkeypatch):
    mp = _build(main_window, monkeypatch, "darwin", DEV)
    knife = mp.mode_buttons["Knife"][0]
    text = knife.palette().color(QPalette.ButtonText)
    accent = line_icons.accentColor(knife.palette())
    _img, off = _inked(knife.icon())
    _img, on = _inked(knife.icon(), checked=True)
    assert {c.rgb() for c in off} == {text.rgb()}
    assert {c.rgb() for c in on} == {accent.rgb()}

    flag = mp.mode_buttons["Flag"][0]
    _img, flag_px = _inked(flag.icon())
    assert {c.rgb() for c in flag_px} == {QColor(*main_window.series.getOption("flag_color")).rgb()}

    # a new flag color re-tints the Flag tool and keeps it an icon
    mp.setFlag(color=(0, 200, 0))
    assert flag.text() == ""
    _img, flag_px = _inked(flag.icon())
    assert {c.rgb() for c in flag_px} == {QColor(0, 200, 0).rgb()}


@pytest.mark.gui
def test_a_palette_change_retints(main_window, monkeypatch, qtbot):
    mp = _build(main_window, monkeypatch, "darwin", DEV)
    # an app style sheet left by an earlier test would override the palette
    app = QApplication.instance()
    sheet = app.styleSheet()
    app.setStyleSheet("")
    red = QColor(250, 10, 10)
    try:
        new = QPalette(main_window.palette())
        new.setColor(QPalette.ButtonText, red)
        main_window.setPalette(new)
        knife = mp.mode_buttons["Knife"][0]
        assert knife.palette().color(QPalette.ButtonText).rgb() == red.rgb()
        qtbot.waitUntil(lambda: {c.rgb() for c in _inked(knife.icon())[1]}
                        == {red.rgb()}, timeout=2000)
        # every tool, not only the one being watched
        ztool = mp.mode_buttons["Ztool"][0]
        assert {c.rgb() for c in _inked(ztool.icon())[1]} == {red.rgb()}
    finally:
        main_window.setPalette(QPalette())
        app.setStyleSheet(sheet)


def _assert_today(mp):
    for name in PNG_TOOLS:
        b = mp.mode_buttons[name][0]
        stripped = name.replace(" ", "").replace("/", "").lower()
        png = QPixmap(os.path.join(loc.img_dir, stripped + ".png"))
        assert b.iconSize() == QSize(40, 40), name
        got = b.icon().pixmap(png.size()).toImage()
        assert _same_image(got, png.toImage()), name
    assert mp.mode_buttons["Flag"][0].text() == "⚑"
    assert mp.mode_buttons["Host"][0].text() == "⎋"
    assert mp.mode_buttons["ROI mode"][0].text() == "ROI"


@pytest.mark.gui
def test_linux_dev_keeps_todays_icons(main_window, monkeypatch):
    _assert_today(_build(main_window, monkeypatch, "linux", DEV))


@pytest.mark.gui
def test_windows_dev_keeps_todays_icons(main_window, monkeypatch):
    _assert_today(_build(main_window, monkeypatch, "win32", DEV))


@pytest.mark.gui
def test_mac_stable_keeps_todays_icons(main_window, monkeypatch):
    _assert_today(_build(main_window, monkeypatch, "darwin", STABLE))


def test_only_the_used_icons_are_vendored():
    files = sorted(os.listdir(line_icons.ICON_DIR))
    assert files == sorted(["LICENSE"] + [n + ".svg" for n in line_icons.TOOL_ICONS.values()])
    with open(os.path.join(line_icons.ICON_DIR, "LICENSE"), encoding="utf-8") as f:
        assert f.read().startswith("ISC License")

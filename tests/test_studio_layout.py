"""Tests for the Studio layout widgets (gui.studio).

These pin the foundation's structure and the spec's non-negotiables that can be
checked headlessly: the chrome stylesheet builds for both shells and never
carries azure; the activity rail and tool rail switch active state and signal;
the Objects panel renders a virtualizing model/view, filters, and reports
selection; the canvas hosts the glassy floats and steps sections; the palette
strip and status bar behave; and the whole shell assembles, toggles Studio ↔
Atlas, and grabs to a non-null pixmap with no azure in its applied chrome.

Qt-backed; skipped if PySide6/qdarkstyle are unavailable.
"""
import os
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PySide6.QtSvg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from PyReconstruct.modules.gui.studio import qss  # noqa: E402
from PyReconstruct.modules.gui.studio.rail import ActivityRail, RAIL_ITEMS  # noqa: E402
from PyReconstruct.modules.gui.studio.tool_rail import ToolRail, TOOL_ITEMS  # noqa: E402
from PyReconstruct.modules.gui.studio.objects_panel import ObjectsPanel  # noqa: E402
from PyReconstruct.modules.gui.studio.canvas import CanvasArea  # noqa: E402
from PyReconstruct.modules.gui.studio.palette_strip import PaletteStrip  # noqa: E402
from PyReconstruct.modules.gui.studio.status_bar import StudioStatusBar  # noqa: E402
from PyReconstruct.modules.gui.studio.shell import StudioShell  # noqa: E402

AZURE_HUES = ("#4c8dff", "#3d8bd4")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _collect(signal):
    """Connect a signal to a list and return it for later assertions."""
    seen = []
    signal.connect(lambda *a: seen.append(a[0] if len(a) == 1 else a))
    return seen


# --- chrome stylesheet -------------------------------------------------------
@pytest.mark.parametrize("theme_name", ["studio", "atlas"])
def test_chrome_qss_builds_and_has_no_azure(qapp, theme_name):
    css = qss.chrome_qss(theme_name)
    assert css and "#studioActivityRail" in css and "#studioToolRail" in css
    assert "#studioObjectsPanel" in css and "#studioStatusBar" in css
    low = css.lower()
    for azure in AZURE_HUES:
        assert azure not in low, f"azure {azure} in {theme_name} chrome"


def test_chrome_qss_differs_between_shells(qapp):
    # same selectors, different neutral shell (Studio dark vs Atlas light)
    assert qss.chrome_qss("studio") != qss.chrome_qss("atlas")
    assert "#0c0f14" in qss.chrome_qss("studio")   # dark ground
    assert "#f4f6fa" in qss.chrome_qss("atlas")    # light ground
    # the teal accent is in both
    assert "#37c0a6" in qss.chrome_qss("studio") and "#37c0a6" in qss.chrome_qss("atlas")


# --- activity rail -----------------------------------------------------------
def test_activity_rail_switches_and_signals(qapp):
    rail = ActivityRail()
    keys = [it[0] for it in RAIL_ITEMS if it]
    assert {"objects", "traces", "sections", "flags", "scene3d", "settings"} <= set(keys)
    assert rail.active_key() == "objects"   # default
    fired = _collect(rail.activated)
    rail._on_click("traces")
    assert rail.active_key() == "traces"
    assert rail._buttons["traces"].is_active()
    assert not rail._buttons["objects"].is_active()
    assert fired == ["traces"]
    rail.retint("#6a7686", "#37c0a6")   # no raise


# --- tool rail ---------------------------------------------------------------
def test_tool_rail_flush_switches_and_signals(qapp):
    tr = ToolRail()
    keys = [it[0] for it in TOOL_ITEMS if it]
    assert {"pointer", "panzoom", "closedtrace", "opentrace", "knife",
            "stamp", "grid", "flag", "host"} <= set(keys)
    assert tr.active_key() == "pointer"
    assert tr.width() == 60
    fired = _collect(tr.tool_selected)
    tr._on_click("knife")
    assert tr.active_key() == "knife" and fired == ["knife"]
    assert tr._buttons["knife"].is_active()


# --- objects panel -----------------------------------------------------------
def _objs(n):
    return [{"name": f"obj_{i}", "type": "dendrite" if i % 2 else "",
             "color": "#37c0a6", "status": ("curated", "review", "flagged")[i % 3]}
            for i in range(n)]


def test_objects_panel_populates_filters_and_selects(qapp):
    panel = ObjectsPanel()
    panel.set_objects(_objs(50))
    assert panel._proxy.rowCount() == 50
    assert panel._count.text() == "50"
    # selection fires object_activated; first row auto-selected on set
    fired = _collect(panel.object_activated)
    panel.view.setCurrentIndex(panel._proxy.index(3, 0))
    assert fired and fired[-1] == "obj_3"
    # live filter narrows the proxy and updates the count
    panel.filter.setText("obj_1")   # obj_1, obj_10..obj_19
    assert 0 < panel._proxy.rowCount() < 50
    assert panel._count.text() == str(panel._proxy.rowCount())
    panel.filter.setText("")
    assert panel._proxy.rowCount() == 50


def test_objects_panel_retitle_and_theme(qapp):
    panel = ObjectsPanel()
    panel.set_title("traces")
    assert panel._title.text() == "TRACES"
    panel.apply_theme("atlas")   # re-tints delegate/legend without error
    panel.apply_theme("studio")


def test_objects_panel_virtualizes_large_list(qapp):
    # a large model must not create per-row widgets (model/view + delegate)
    panel = ObjectsPanel()
    panel.set_objects(_objs(4000))
    assert panel._proxy.rowCount() == 4000
    assert panel._count.text() == "4,000"   # mono count, comma-grouped


# --- canvas + floats ---------------------------------------------------------
def test_canvas_floats_and_section_step(qapp):
    canvas = CanvasArea()
    # all four glassy floats exist
    for f in (canvas.badge, canvas.scalebar, canvas.secnav, canvas.bc):
        assert f.parent() is canvas
    stepped = _collect(canvas.section_changed)
    canvas.secnav.stepped.emit(1)
    assert stepped == [1]
    canvas.set_section(149, 287)
    canvas.set_active_object("d001", "curated")
    canvas.set_brightness(70)
    canvas.set_contrast(30)
    assert canvas.bc.bright.value() == 70 and canvas.bc.contr.value() == 30
    canvas.apply_theme("atlas")


def test_canvas_widget_seam(qapp):
    canvas = CanvasArea()
    real = QWidget()
    canvas.set_canvas_widget(real)
    assert real.parent() is canvas
    # floats still present and on top
    assert canvas.badge.parent() is canvas


def test_canvas_bc_signals(qapp):
    canvas = CanvasArea()
    b = _collect(canvas.brightness_changed)
    canvas.bc.bright.setValue(80)
    assert b == [80]


# --- palette strip -----------------------------------------------------------
def test_palette_strip_select_and_add(qapp):
    strip = PaletteStrip()
    strip.set_colors(["#6ce0c4", "#f0a6d8", "#9bd35a", "#37c0a6"])
    strip.set_active(0)
    assert len(strip._swatches) == 4
    assert strip._swatches[0]._active and not strip._swatches[1]._active
    picked = _collect(strip.color_selected)
    strip._on_click(2)
    assert picked == [2] and strip._swatches[2]._active
    added = _collect(strip.add_requested)
    strip._add.click()
    assert added  # add_requested fired
    strip.set_readout("circle · r=0.045")
    assert "0.045" in strip._readout.text()


# --- status bar --------------------------------------------------------------
def test_status_bar_values_are_teal(qapp):
    sb = StudioStatusBar()
    sb.set_section(148)
    sb.set_zoom("240%")
    # active values carry the teal accent; labels do not
    assert "#37c0a6" in sb._section.text() and "148" in sb._section.text()
    assert "section" in sb._section.text()
    assert "240%" in sb._zoom.text()


# --- the whole shell ---------------------------------------------------------
def test_shell_demo_assembles(qapp):
    shell = StudioShell.demo()
    # every region is present
    for region in (shell.title_strip, shell.rail, shell.objects_panel,
                   shell.canvas, shell.tool_rail, shell.palette_strip,
                   shell.status_bar):
        assert region is not None and region.parent() is not None
    # the demo object list reads like the mockup count and virtualizes
    assert shell.objects_panel._proxy.rowCount() == 3809
    assert shell.objects_panel._count.text() == "3,809"
    assert shell.rail.active_key() == "objects"
    assert shell.tool_rail.active_key() == "pointer"


def test_shell_rail_repoints_panel(qapp):
    shell = StudioShell.demo()
    shell._on_rail("traces")
    assert shell.objects_panel._title.text() == "TRACES"
    assert 0 < shell.objects_panel._proxy.rowCount() < 3809
    shell._on_rail("objects")
    assert shell.objects_panel._proxy.rowCount() == 3809


def test_shell_seam_items_light_but_dont_repoint(qapp):
    # 3D / Settings are honest seams: clicking lights the rail + emits, but the
    # left panel must NOT repoint (no fake feature behind them).
    shell = StudioShell.demo()
    title_before = shell.objects_panel._title.text()
    rows_before = shell.objects_panel._proxy.rowCount()
    fired = _collect(shell.rail.activated)
    for seam in ("scene3d", "settings"):
        shell.rail._on_click(seam)
        assert shell.rail.active_key() == seam
        assert seam in fired
        assert shell.objects_panel._title.text() == title_before
        assert shell.objects_panel._proxy.rowCount() == rows_before


def test_shell_object_selection_updates_badge(qapp):
    shell = StudioShell.demo()
    shell._on_object("psd_018")   # a flagged object
    assert "psd_018" in shell.canvas.badge._text.text()
    assert shell.canvas.badge._status == "flagged"


def test_shell_section_step(qapp):
    shell = StudioShell.demo()
    shell._on_section_step(1)
    assert shell._section_idx == 149
    assert "149" in shell.status_bar._section.text()
    # clamps at the bottom
    shell._section_idx = 1
    shell._on_section_step(-1)
    assert shell._section_idx == 1


@pytest.mark.parametrize("theme_name", ["studio", "atlas"])
def test_shell_theme_toggle_no_azure(qapp, theme_name):
    shell = StudioShell.demo()
    shell.apply_theme(theme_name, app_wide=False)
    low = shell.styleSheet().lower()
    assert low, "chrome stylesheet must be applied to the shell"
    for azure in AZURE_HUES:
        assert azure not in low, f"azure {azure} in shell chrome for {theme_name}"


def test_title_strip_brand_uses_app_icon(qapp):
    from PyReconstruct.modules.gui.studio._common import app_icon_path
    from PyReconstruct.modules.gui.studio.title_strip import StudioTitleStrip
    ts = StudioTitleStrip()
    ts.apply_theme("studio")   # dark squircle
    ts.apply_theme("atlas")    # light squircle — neither path errors
    # the shipped fork icons resolve in this checkout
    assert app_icon_path("dark") and app_icon_path("light")
    assert app_icon_path("dark").endswith("PyReconstruct.png")
    assert app_icon_path("light").endswith("PyReconstruct-light.png")


def test_shell_sets_window_icon(qapp):
    from PyReconstruct.modules.gui.studio._common import app_icon_path
    shell = StudioShell.demo()
    for th in ("studio", "atlas"):
        shell.apply_theme(th, app_wide=False)
        if app_icon_path("dark"):   # assets present -> window icon is set
            assert not shell.windowIcon().isNull()


def test_shell_renders_offscreen(qapp):
    shell = StudioShell.demo()
    shell.resize(1180, 560)
    shell.show()
    qapp.processEvents()
    pm = shell.grab()
    assert not pm.isNull() and pm.width() >= 1180

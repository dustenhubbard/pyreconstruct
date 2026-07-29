"""Menu shortcut keybinds get breathing room from their labels.

Qt right-justifies a shortcut against its menu item's right edge, but the
native macOS style sizes CT_MenuItem so tightly that the widest label runs to
within ~5 px of the shortcut column (measured by pixel-scanning a QMenu.grab()
of the real File menu items: label ink ended at x=153, shortcut ink began at
x=158, while the item's own left padding was ~19 px). PyReconstruct's menubar
is in-window -- setNativeMenuBar(False) -- so every menu is Qt-drawn and the
fix belongs in the style layer.

``MenuShortcutSpacingStyle`` (a QProxyStyle installed once in run.py) widens
CT_MenuItem by one line-height of the menu font for every row of a menu that
shows shortcuts, which pushes the right-aligned shortcut column further right
while leaving ALL painting to the native style. A stylesheet was rejected with
evidence: any ``QMenu::item`` rule swaps the item's layout to the CSS box
model, which visibly strips the native left padding (label ink moved from
x=18.5 to x=0.5 in the same grab harness).

"Every row", not "the rows with a shortcut", is the load-bearing part, and it
is what section 3 below exists for. Qt lays a menu out at a single width for
all of its items: QMenuPrivate::updateActionRects takes the *maximum* item
width and only then adds the shortcut column. Widening just the shortcut rows
therefore moves the column only when a shortcut row happens to be the widest
row in that menu -- which is why the first version of this style did nothing
whatsoever to View (widest row: the shortcut-less "Set zoom when finding
contours...") and only 12 of 14 px to Lists (where "Series history" nearly ties
the widened rows), while looking correct on File. Measured, real menubar,
macOS native style:

    menu width      before  tab-rows-only  every-row
    File               203       217           219
    Lists              148       160           164
    Alignments         224       230           240
    View               270       270 (!)       286

These tests prove the mechanism on a per-widget style (equivalent sizing path,
no mutation of the suite-wide QApplication style): the width grows by one
line-height, the *rendered* pixel gap between label ink and shortcut ink grows
accordingly, menus that show no shortcut are untouched, and -- section 3 -- all
of that holds when the widest row is one without a shortcut.
"""

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu


ITEMS = [
    # (text, shortcut) -- real File menu rows; "Restart PyReconstruct" is the
    # widest labelled+shortcut row and therefore the cramped one
    ("Open series...", "Ctrl+O"),
    ("Save", "Ctrl+S"),
    ("Restart PyReconstruct", "Ctrl+R"),
    ("Quit", "Ctrl+Q"),
    ("Change username...", ""),
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(["test"])
    # A standalone QMenu counts as a "context menu", and on macOS Qt neither
    # shows nor SIZES FOR shortcuts in context menus by default. The app's
    # menus hang off a (non-native) QMenuBar, where shortcuts do appear, so
    # flip the attribute to reproduce the menubar-dropdown layout, and restore
    # it afterwards.
    before = app.testAttribute(Qt.AA_DontShowShortcutsInContextMenus)
    app.setAttribute(Qt.AA_DontShowShortcutsInContextMenus, False)
    yield app
    app.setAttribute(Qt.AA_DontShowShortcutsInContextMenus, before)


class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _MainWindowStub(_Anything):
    """The MainWindow surface return_list_menu touches."""

    def __init__(self, series):
        super().__init__(series=series, field=_Anything(), mouse_palette=_Anything())


@pytest.fixture(scope="module")
def real_shortcut_series(tmp_path_factory):
    """The real Series, so getOption resolves the real default shortcuts -- the
    bare-Series path Lists and Alignments use (newAction's ``else`` branch)."""
    import os
    import shutil

    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes.series import Series

    fixture = os.path.join(
        os.path.dirname(__file__), "..", "PyReconstruct",
        "assets", "checker", "files", "shapes1.jser",
    )
    if not os.path.exists(fixture):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path_factory.mktemp("series") / "s.jser")
    shutil.copyfile(fixture, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def _menu(qapp, spaced: bool, items=ITEMS) -> QMenu:
    menu = QMenu()
    if spaced:
        from PyReconstruct.modules.gui.utils import MenuShortcutSpacingStyle

        # per-widget install: same sizeFromContents path QMenu uses, without
        # touching the QApplication style other tests share
        style = MenuShortcutSpacingStyle()
        style.setParent(menu)
        menu.setStyle(style)
    for text, kbd in items:
        action = QAction(text, menu)
        if kbd:
            action.setShortcut(kbd)
        menu.addAction(action)
    menu.resize(menu.sizeHint())
    return menu


# The scan is limited to a horizontal band through the middle of the row, inset
# from its left and right edges. Both restrictions are needed to make the
# measurement portable: scanning the full row counted the menu frame and the
# fusion style's row edges as "ink", which on the offscreen platform (fusion)
# marked every single column as ink and reported a 1 px gap for rows whose
# shortcut was plainly rendered. Text lives in the middle band, frames do not.
_SCAN_INSET = 4          # px, clear of the menu frame and row edges
_SCAN_HALF_BAND = 0.22   # fraction of the row height above/below its centre


def _ink_columns(menu: QMenu, action: QAction):
    """x-positions (logical px, relative to the scanned region) of every column
    of the rendered row that contains non-background pixels."""
    image = menu.grab().toImage()
    scale = image.devicePixelRatio()
    rect = menu.actionGeometry(action)

    x0 = int((rect.x() + _SCAN_INSET) * scale)
    x1 = int((rect.x() + rect.width() - _SCAN_INSET) * scale)
    middle = rect.y() + rect.height() / 2
    y0 = int((middle - rect.height() * _SCAN_HALF_BAND) * scale)
    y1 = int((middle + rect.height() * _SCAN_HALF_BAND) * scale)

    # background = the band's most common color
    from collections import Counter

    counts = Counter(
        image.pixel(x, y) for y in range(y0, y1) for x in range(x0, x1)
    )
    background = counts.most_common(1)[0][0]

    def contrasts(pixel):
        return (
            abs(((pixel >> 16) & 0xFF) - ((background >> 16) & 0xFF))
            + abs(((pixel >> 8) & 0xFF) - ((background >> 8) & 0xFF))
            + abs((pixel & 0xFF) - (background & 0xFF))
        ) > 90

    return [
        (x - x0) / scale
        for x in range(x0, x1)
        if any(contrasts(image.pixel(x, y)) for y in range(y0, y1))
    ]


def _label_shortcut_gap(menu: QMenu, action: QAction) -> float:
    """The widest run of background between two runs of ink -- i.e. the gap
    between where the label ends and the shortcut begins."""
    columns = _ink_columns(menu, action)
    assert columns, "no rendered ink found in the item -- did shortcuts render?"
    return max(
        (b - a for a, b in zip(columns, columns[1:])), default=0.0
    )


def _widest_action(menu: QMenu) -> QAction:
    return next(a for a in menu.actions() if a.text() == "Restart PyReconstruct")


# --------------------------------------------------------------------------- #
# sizing: deterministic, style-arithmetic level
# --------------------------------------------------------------------------- #
def test_a_menu_with_shortcuts_gains_exactly_one_line_height_of_width(qapp):
    plain = _menu(qapp, spaced=False)
    spaced = _menu(qapp, spaced=True)
    extra = spaced.fontMetrics().height()
    assert spaced.sizeHint().width() == plain.sizeHint().width() + extra


def test_menus_without_shortcuts_are_untouched(qapp):
    items = [("Randomize project...", ""), ("De-randomize project...", "")]
    plain = _menu(qapp, spaced=False, items=items)
    spaced = _menu(qapp, spaced=True, items=items)
    assert spaced.sizeHint().width() == plain.sizeHint().width()
    assert spaced.sizeHint().height() == plain.sizeHint().height()


# --------------------------------------------------------------------------- #
# rendering: the gap the user actually sees, measured off a grab
# --------------------------------------------------------------------------- #
def test_rendered_gap_between_label_and_shortcut_grows_by_the_extra(qapp):
    """Pixel evidence, not eyeballing: in the widest row, the largest
    background run between label ink and shortcut ink must grow by about the
    line-height (small tolerance for glyph side-bearings)."""
    plain = _menu(qapp, spaced=False)
    spaced = _menu(qapp, spaced=True)
    extra = spaced.fontMetrics().height()

    gap_before = _label_shortcut_gap(plain, _widest_action(plain))
    gap_after = _label_shortcut_gap(spaced, _widest_action(spaced))

    assert gap_after >= gap_before + 0.75 * extra, (
        f"gap only went {gap_before:.1f}px -> {gap_after:.1f}px "
        f"(extra={extra}px): the widened item did not push the shortcut over"
    )


def test_shortcut_column_stays_right_justified(qapp):
    """The widening must land between label and shortcut, not to the right of
    the shortcut: the last ink of the row keeps the same distance from the
    item's right edge as in the unspaced menu."""
    plain = _menu(qapp, spaced=False)
    spaced = _menu(qapp, spaced=True)

    def right_margin(menu):
        action = _widest_action(menu)
        scanned_width = menu.actionGeometry(action).width() - 2 * _SCAN_INSET
        return scanned_width - _ink_columns(menu, action)[-1]

    assert abs(right_margin(spaced) - right_margin(plain)) <= 2.0


# --------------------------------------------------------------------------- #
# 3. the max-width interaction: menus of the Lists / View shape
# --------------------------------------------------------------------------- #
# The maintainer click-tested the first version of this style and reported Lists
# as "looking untouched" while File was visibly improved. The cause is Qt's
# single-width-per-menu layout, not the shortcut code path: a menu whose widest
# row carries NO shortcut absorbs a per-shortcut-row widening entirely. Both
# shapes below are regression cases for that, and both are unaffected by the
# tab-rows-only version of the style.
#
# Note this is NOT about how the shortcut was configured. Lists and Alignments
# reach newAction's `else` branch (a bare Series -> kbd.getOption(act_name)),
# unlike File's plain strings, but by the time a menu is laid out the shortcut
# is a QKeySequence on the QAction either way -- verified: with the real series,
# objectlist_act resolves to Ctrl+Shift+O and its style option carries the tab.
LIST_SHAPED_ITEMS = [
    # the real Lists menu: short labels with shortcuts, and one longer
    # shortcut-less row ("Series history") that ties/beats them on width
    ("Object list", "Ctrl+Shift+O"),
    ("Trace list", "Ctrl+Shift+T"),
    ("Section list", "Ctrl+Shift+S"),
    ("Z-trace list", "Ctrl+Shift+Z"),
    ("Flag list", "Ctrl+Shift+F"),
    ("Series history", ""),
]

# the extreme of the same shape, from the real View menu: the widest row by far
# has no shortcut, so the tab-rows-only widening moved nothing at all (measured:
# View stayed at 270 px)
VIEW_SHAPED_ITEMS = [
    ("Set view to image", "Home"),
    ("Set zoom when finding contours...", ""),
    ("Toggle curation in object lists", "Ctrl+Shift+C"),
]


@pytest.mark.parametrize(
    "items,shortcut_row,strictly_absorbing",
    [
        (LIST_SHAPED_ITEMS, "Object list", False),
        (VIEW_SHAPED_ITEMS, "Toggle curation in object lists", True),
    ],
    ids=["Lists-shaped", "View-shaped"],
)
def test_shortcut_column_moves_even_when_the_widest_row_has_no_shortcut(
    qapp, items, shortcut_row, strictly_absorbing
):
    """The regression the maintainer caught: these menus must gain the same
    offset File does, though no shortcut row is the widest row.

    ``strictly_absorbing`` distinguishes what each case can promise, because
    "which row is widest" depends on the platform's font metrics:

    * View-shaped is strictly absorbing -- its shortcut-less row beats every
      shortcut row by MORE than the widening, so a tab-rows-only style provably
      moves nothing, on any style. This is the deterministic guard, and the one
      that fails in CI if the mechanism regresses (measured under
      offscreen/fusion: 300 px -> 300 px).
    * Lists-shaped is the real Lists menu, where "Series history" merely ties
      the widened shortcut rows. That is an absorbing shape under the macOS
      native metrics (where a tab-rows-only style delivered 12 of 14 px) but not
      under fusion, where the widened rows do become the widest. So it is kept
      as a real-world shape that must gain the full offset, not as a proof that
      the old mechanism fails everywhere.
    """
    plain = _menu(qapp, spaced=False, items=items)
    spaced = _menu(qapp, spaced=True, items=items)
    extra = spaced.fontMetrics().height()

    # the premise these cases rest on: the widest LABEL belongs to a row with
    # no shortcut, which is what let the first version's widening be absorbed
    def label_width(text):
        return plain.fontMetrics().horizontalAdvance(text)

    widest_without = max(label_width(t) for t, kbd in items if not kbd)
    widest_with = max(label_width(t) for t, kbd in items if kbd)
    margin = extra if strictly_absorbing else 0
    assert widest_without >= widest_with + margin, (
        "premise broken: pick labels where a shortcut-less row is the widest"
        + (" by more than one line-height" if strictly_absorbing else "")
    )

    assert spaced.sizeHint().width() == plain.sizeHint().width() + extra

    action_before = next(a for a in plain.actions() if a.text() == shortcut_row)
    action_after = next(a for a in spaced.actions() if a.text() == shortcut_row)
    gap_before = _label_shortcut_gap(plain, action_before)
    gap_after = _label_shortcut_gap(spaced, action_after)
    assert gap_after >= gap_before + 0.75 * extra, (
        f"{shortcut_row!r}: gap only went {gap_before:.1f}px -> {gap_after:.1f}px "
        f"(extra={extra}px) -- the shortcut column did not move"
    )


def test_real_lists_menu_gains_the_offset_with_series_configured_shortcuts(
    qapp, real_shortcut_series
):
    """End to end on the real definition and the real bare-Series code path:
    return_list_menu built through newAction, shortcuts resolved from series
    options, measured on rendered pixels."""
    from PyReconstruct.modules.gui.main.menubar import return_list_menu
    from PyReconstruct.modules.gui.utils.utils import addItem

    def build(spaced):
        from PySide6.QtWidgets import QWidget

        holder = QWidget()
        container = QMenu(holder)
        if spaced:
            from PyReconstruct.modules.gui.utils import MenuShortcutSpacingStyle

            style = MenuShortcutSpacingStyle()
            style.setParent(holder)
            container.setStyle(style)
        addItem(holder, container, return_list_menu(_MainWindowStub(real_shortcut_series)))
        menu = holder.listsmenu
        if spaced:
            menu.setStyle(style)
        menu.resize(menu.sizeHint())
        return holder, menu

    holder_plain, plain = build(spaced=False)
    holder_spaced, spaced = build(spaced=True)
    extra = spaced.fontMetrics().height()

    # the series option really is what supplies the key here
    assert real_shortcut_series.getOption("objectlist_act") == "Ctrl+Shift+O"
    assert holder_plain.objectlist_act.shortcut().toString() == "Ctrl+Shift+O"

    assert spaced.sizeHint().width() == plain.sizeHint().width() + extra

    gap_before = _label_shortcut_gap(plain, holder_plain.objectlist_act)
    gap_after = _label_shortcut_gap(spaced, holder_spaced.objectlist_act)
    assert gap_after >= gap_before + 0.75 * extra, (
        f"real Lists menu: gap only went {gap_before:.1f}px -> {gap_after:.1f}px"
    )

    holder_plain.deleteLater()
    holder_spaced.deleteLater()


def test_a_menu_that_hides_its_shortcuts_is_left_alone(qapp):
    """Qt decides whether a shortcut column is drawn at all (on macOS it is
    hidden in context menus by default). Where nothing is drawn, the extra space
    would buy nothing, so the style asks Qt via the option text rather than
    assuming a QAction with a shortcut means a visible shortcut."""
    before = qapp.testAttribute(Qt.AA_DontShowShortcutsInContextMenus)
    qapp.setAttribute(Qt.AA_DontShowShortcutsInContextMenus, True)
    try:
        plain = _menu(qapp, spaced=False)
        spaced = _menu(qapp, spaced=True)
        # nothing is rendered to space out, so nothing is widened
        assert spaced.sizeHint().width() == plain.sizeHint().width()
    finally:
        qapp.setAttribute(Qt.AA_DontShowShortcutsInContextMenus, before)


# --------------------------------------------------------------------------- #
# wiring: the app installs the style once, at QApplication creation
# --------------------------------------------------------------------------- #
def test_run_py_installs_the_spacing_style():
    """run.py is never imported by the suite (it launches the app), so the
    wiring is pinned at source level: the style is set right after the
    QApplication is created, where it survives setTheme's stylesheet swaps."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "PyReconstruct" / "run.py"
    ).read_text(encoding="utf-8")
    created = source.index("app = QApplication(sys.argv)")
    assert "app.setStyle(MenuShortcutSpacingStyle())" in source[created:]

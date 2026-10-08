"""The What's new dialog's restyled notes and its show-after-update checkbox.

The notes browser renders each version as a large bold heading with its date
in the secondary gray, every item as a paragraph that hangs from a dash
marker, and the body in a palette-derived gray that follows the theme. The
footer's "Show this changelog window after each update?" checkbox is the
stored popup preference stated the way round a reader expects: it reads and
writes the inverse of ``WHATSNEW_SUPPRESS_KEY``, the same key the Help menu
toggle uses.
"""

import pytest

from PySide6.QtGui import QPalette, QTextFormat
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.main import first_launch as F

pytestmark = pytest.mark.gui


NOTES = """# What's New

## [1.21.0] — 2026-07-20

#### New

- **Added the shiny new thing.** It shines on Windows, macOS, and Linux once
  this version is installed, and this line is long enough to wrap in the
  dialog so the hanging indent has something to hang.
- **A second thing.** Short.

#### Improved

- **Faster.** About twice as fast.

## [1.20.3] — 2026-06-29

- Fixed the old thing.
"""


class FakeSettings:
    """A QSettings-shaped dict, so the checkbox can be driven without Qt I/O."""

    def __init__(self, data=None):
        self._d = dict(data or {})
        self.writes = []

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val
        self.writes.append((key, val))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


def _dialog(settings=None, **kwargs):
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    content = F.whats_new_content("1.21.0", last_seen="1.20.1", text=NOTES)
    return WhatsNewDialog(None, "1.21.0", content=content, settings=settings,
                          url="https://example.test/releases", **kwargs)


def _blocks(dlg):
    doc = dlg._notes.document()
    block = doc.begin()
    while block.isValid():
        yield block
        block = block.next()


def _fragments(block):
    it = block.begin()
    while not it.atEnd():
        yield it.fragment()
        it += 1


def _foreground(fragment):
    fmt = fragment.charFormat()
    if not fmt.hasProperty(QTextFormat.ForegroundBrush):
        return None
    return fmt.foreground().color().name()


# ---- the checkbox ------------------------------------------------------------

@pytest.mark.parametrize("stored,checked", [
    (True, False), ("true", False), (False, True), ("false", True),
])
def test_show_after_update_box_opens_on_the_inverse_of_the_stored_key(qapp, stored, checked):
    """Checked means the popup shows: the box is the stored suppression, inverted.

    Both spellings of a stored bool are covered, because the redirected store
    is INI and hands a bool back as a string.
    """
    settings = FakeSettings({F.WHATSNEW_SUPPRESS_KEY: stored})
    dlg = _dialog(settings=settings)
    try:
        assert dlg._show_box.isChecked() is checked
        assert dlg._show_box.text() == (
            "Show this changelog window after each update?"
        )
        assert settings.writes == []           # opening the dialog writes nothing
    finally:
        dlg.deleteLater()


def test_show_after_update_box_opens_on_the_default_when_nothing_is_stored(qapp):
    """With no stored preference the box shows the default, inverted."""
    settings = FakeSettings()
    dlg = _dialog(settings=settings)
    try:
        expected = not F.whats_new_suppressed(F.WHATSNEW_SUPPRESS_DEFAULT)
        assert dlg._show_box.isChecked() is expected
    finally:
        dlg.deleteLater()


def test_toggling_the_box_writes_the_inverse_of_the_key_and_nothing_else(qapp):
    """Each toggle writes ``WHATSNEW_SUPPRESS_KEY`` as ``not checked``, at once.

    Only that key: the once-per-version record is left alone, which is what
    lets the Help toggle (or this box, later) hand the ordinary rules back
    with a missed version bump intact. The dialog stays open; Close closes.
    """
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.1",
                             F.WHATSNEW_SUPPRESS_KEY: False})
    dlg = _dialog(settings=settings)
    try:
        dlg.show()
        assert dlg._show_box.isChecked()
        dlg._show_box.setChecked(False)
        assert settings.writes == [(F.WHATSNEW_SUPPRESS_KEY, True)]
        assert dlg.isVisible()
        dlg._show_box.setChecked(True)
        assert settings.writes == [(F.WHATSNEW_SUPPRESS_KEY, True),
                                   (F.WHATSNEW_SUPPRESS_KEY, False)]
        assert settings.value(F.WHATSNEW_KEY) == "1.20.1"
    finally:
        dlg.deleteLater()


def test_close_is_the_only_button_and_the_default(qapp):
    """One Close button, the default, and no "Don't show again" button."""
    from PySide6.QtWidgets import QPushButton, QCheckBox
    dlg = _dialog(settings=FakeSettings())
    try:
        buttons = dlg.findChildren(QPushButton)
        assert [b.text() for b in buttons] == ["Close"]
        assert buttons[0].isDefault() is True
        assert [c.text() for c in dlg.findChildren(QCheckBox)] == [
            "Show this changelog window after each update?"
        ]
        dlg.show()
        buttons[0].click()
        assert not dlg.isVisible()
    finally:
        dlg.deleteLater()


def test_box_and_link_sit_above_byline_and_close(qapp):
    """Two footer rows: checkbox left and link right directly under the notes,
    then byline left and Close bottom right."""
    from PySide6.QtWidgets import QLabel, QPushButton
    dlg = _dialog(settings=FakeSettings())
    try:
        dlg.show()
        dlg.resize(760, 620)
        dlg.layout().activate()
        close = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Close")
        link = next(lab for lab in dlg.findChildren(QLabel)
                    if "All release notes on GitHub" in lab.text())
        box, byline, notes = (dlg._show_box.geometry(), dlg._byline.geometry(),
                              dlg._notes.geometry())
        link, close = link.geometry(), close.geometry()

        def same_row(a, b):
            return a.top() < b.bottom() and b.top() < a.bottom()

        assert box.top() >= notes.bottom()
        assert same_row(box, link) and box.right() < link.left()
        assert same_row(byline, close) and byline.right() < close.left()
        assert byline.top() >= box.bottom() and byline.top() >= link.bottom()
        assert close.top() >= link.bottom()
        assert close.right() >= link.right() - 1        # bottom right
        assert box.left() == pytest.approx(byline.left(), abs=1)
    finally:
        dlg.deleteLater()


# ---- the notes ---------------------------------------------------------------

def test_items_hang_from_a_dash_marker(qapp):
    """Every item is a paragraph starting with the dash marker, in no list,
    with a hanging indent: left margin equal to the marker's width and the
    first line pulled back by the same amount."""
    from PyReconstruct.modules.gui.dialog.whats_new import ITEM_MARKER
    dlg = _dialog(settings=FakeSettings())
    try:
        items = [b for b in _blocks(dlg) if b.text().startswith(ITEM_MARKER)]
        assert len(items) == NOTES.count("\n- ")
        assert not any(b.textList() is not None for b in _blocks(dlg))
        for block in items:
            fmt = block.blockFormat()
            assert fmt.leftMargin() > 0
            assert fmt.textIndent() == pytest.approx(-fmt.leftMargin())
            assert fmt.bottomMargin() > 0            # room between items
        assert "— Added the shiny new thing." in dlg._notes.toPlainText()
    finally:
        dlg.deleteLater()


def test_items_wrap_under_their_first_word_not_the_marker(qapp):
    """Rendered, a wrapped item's second line starts where its first word does.

    The margins above are the recipe; this checks the result in the laid-out
    document at the notes' own font size, so a size change that left the
    hang measured in a different font would show here.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import ITEM_MARKER
    dlg = _dialog(settings=FakeSettings())
    try:
        dlg.resize(760, 640)
        dlg.show()
        QApplication.instance().processEvents()
        block = next(b for b in _blocks(dlg) if "shiny new thing" in b.text())
        layout = block.layout()
        assert layout.lineCount() >= 2, "the fixture item did not wrap"
        first, second = layout.lineAt(0), layout.lineAt(1)
        first_word = first.cursorToX(len(ITEM_MARKER))[0]
        marker = first.cursorToX(0)[0]
        second_start = second.cursorToX(second.textStart())[0]
        assert second_start == pytest.approx(first_word, abs=1.0)
        assert second_start > marker + 1
    finally:
        dlg.deleteLater()


def test_notes_are_larger_than_the_dialog_font_with_open_line_spacing(qapp):
    """The notes sit NOTES_SIZE_STEP above the dialog's font, and every
    non-heading paragraph takes the proportional NOTES_LINE_HEIGHT, which
    the layout honors: a wrapped item's lines are that much taller than the
    font's own line."""
    from PySide6.QtGui import QFontMetricsF, QTextBlockFormat
    from PyReconstruct.modules.gui.dialog.whats_new import (
        NOTES_SIZE_STEP, NOTES_LINE_HEIGHT,
    )
    assert 1 <= NOTES_SIZE_STEP <= 2
    assert NOTES_LINE_HEIGHT == 150
    dlg = _dialog(settings=FakeSettings())
    try:
        doc = dlg._notes.document()
        assert doc.defaultFont().pointSizeF() == pytest.approx(
            dlg._notes.font().pointSizeF() + NOTES_SIZE_STEP)
        body = [b for b in _blocks(dlg) if not b.blockFormat().headingLevel()]
        assert body
        for block in body:
            fmt = block.blockFormat()
            assert fmt.lineHeightType() == QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
            assert fmt.lineHeight() == NOTES_LINE_HEIGHT

        dlg.resize(760, 640)
        dlg.show()
        QApplication.instance().processEvents()
        block = next(b for b in body if "shiny new thing" in b.text())
        layout = block.layout()
        pitch = layout.lineAt(1).y() - layout.lineAt(0).y()
        font_line = QFontMetricsF(doc.defaultFont()).height()
        assert pitch == pytest.approx(font_line * NOTES_LINE_HEIGHT / 100, rel=0.1)
    finally:
        dlg.deleteLater()


def test_versions_are_further_apart_than_items(qapp):
    """The gap above a version heading is clearly larger than between items."""
    from PyReconstruct.modules.gui.dialog.whats_new import ITEM_GAP, VERSION_GAP
    assert VERSION_GAP >= 3 * ITEM_GAP
    assert ITEM_GAP >= 8


def test_version_headings_are_large_and_bold_with_the_date_secondary(qapp):
    """A version heading is larger than the body and bold; the date after it
    is body-sized, normal weight, in the secondary gray; and a gap separates
    the second version from the first."""
    from PyReconstruct.modules.gui.dialog.whats_new import (
        secondary_text_color, VERSION_GAP,
    )
    dlg = _dialog(settings=FakeSettings())
    try:
        base = dlg._notes.document().defaultFont().pointSizeF()
        secondary = secondary_text_color(dlg._notes.palette()).name()
        headings = [b for b in _blocks(dlg) if b.blockFormat().headingLevel() == 3]
        assert [b.text().split(" ")[0] for b in headings] == ["1.21.0", "1.20.3"]
        for i, block in enumerate(headings):
            frags = list(_fragments(block))
            version, date = frags[0], frags[-1]
            assert version.text().startswith(block.text().split(" ")[0])
            assert version.charFormat().fontWeight() >= 700
            assert version.charFormat().fontPointSize() > base
            assert _foreground(version) is None      # the full text color
            assert date.text().startswith(" — ")
            assert date.charFormat().fontWeight() < 700
            assert date.charFormat().fontPointSize() == pytest.approx(base)
            assert _foreground(date) == secondary
            assert block.blockFormat().topMargin() == (0 if i == 0 else VERSION_GAP)
        types = [b for b in _blocks(dlg) if b.blockFormat().headingLevel() == 4]
        assert [b.text() for b in types] == ["New", "Improved"]
        for block in types:
            frag = next(_fragments(block))
            assert frag.charFormat().fontWeight() >= 700
            assert frag.charFormat().fontPointSize() == pytest.approx(base)
    finally:
        dlg.deleteLater()


def _body_colors(dlg):
    """The set of foreground colors across every non-heading fragment."""
    colors = set()
    for block in _blocks(dlg):
        if block.blockFormat().headingLevel():
            continue
        for frag in _fragments(block):
            colors.add(_foreground(frag))
    return colors


def test_body_text_paints_in_the_notes_gray_between_background_and_text(qapp):
    """Every item fragment, bold claim included, carries the notes gray, and
    that gray sits strictly between the dialog background and its text."""
    from PyReconstruct.modules.gui.dialog.whats_new import notes_text_color
    dlg = _dialog(settings=FakeSettings())
    try:
        palette = dlg._notes.palette()
        gray = notes_text_color(palette)
        assert _body_colors(dlg) == {gray.name()}
        text = palette.color(QPalette.Active, QPalette.WindowText)
        bg = palette.color(QPalette.Active, QPalette.Window)
        lo, hi = sorted((text.lightness(), bg.lightness()))
        assert lo < gray.lightness() < hi
    finally:
        dlg.deleteLater()


def test_notes_gray_follows_the_dark_theme_and_a_live_switch(qapp):
    """Under the dark theme the gray is lighter than the dark background, and a
    dialog already open when the theme switches recolors to what a dialog
    built fresh under the new theme gets."""
    import qdarkstyle
    app = QApplication.instance()
    previous = app.styleSheet()
    switched = fresh = None
    try:
        app.setStyleSheet("")
        app.setPalette(app.style().standardPalette())
        switched = _dialog(settings=FakeSettings())
        light = _body_colors(switched)
        assert len(light) == 1

        app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6())
        fresh = _dialog(settings=FakeSettings())
        fresh.show()
        app.processEvents()
        dark = _body_colors(fresh)
        assert len(dark) == 1
        palette = fresh._notes.palette()
        bg = palette.color(QPalette.Active, QPalette.Window)
        from PySide6.QtGui import QColor
        assert QColor(next(iter(dark))).lightness() > bg.lightness()
        assert bg.lightness() < 128, "qdark did not reach the browser's palette"
        assert dark != light

        switched.show()
        app.processEvents()
        assert _body_colors(switched) == dark
    finally:
        for dlg in (switched, fresh):
            if dlg is not None:
                dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


def _contrast(a, b):
    """WCAG contrast ratio between two QColors, 1 to 21."""
    def luminance(color):
        def channel(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
                + 0.0722 * channel(color.blue()))
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_notes_and_secondary_grays_clear_their_contrast_floors(qapp, theme):
    """Against the dialog background, the notes gray clears 7:1 and the
    secondary gray (the date beside each version, the footer line) clears
    4.5:1, measured on the palette each widget really paints from, in both
    themes the app has."""
    import qdarkstyle
    from PyReconstruct.modules.gui.dialog.whats_new import (
        notes_text_color, secondary_text_color,
    )
    app = QApplication.instance()
    previous = app.styleSheet()
    dlg = None
    try:
        if theme == "dark":
            app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6())
        else:
            app.setStyleSheet("")
            app.setPalette(app.style().standardPalette())
        dlg = _dialog(settings=FakeSettings())
        dlg.show()
        app.processEvents()
        for widget, color_of, floor in (
            (dlg._notes, notes_text_color, 7.0),
            (dlg._notes, secondary_text_color, 4.5),
            (dlg._byline, secondary_text_color, 4.5),
        ):
            palette = widget.palette()
            bg = palette.color(QPalette.Active, QPalette.Window)
            ratio = _contrast(color_of(palette), bg)
            assert ratio >= floor, (
                f"{theme}: {color_of.__name__} on {bg.name()} is {ratio:.2f}:1"
            )
        if theme == "dark":
            assert dlg._notes.palette().color(QPalette.Window).lightness() < 128
    finally:
        if dlg is not None:
            dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


def test_notes_browser_is_flat_on_the_dialog(qapp):
    """No frame, and the viewport shows the dialog background through it."""
    from PySide6.QtWidgets import QFrame
    dlg = _dialog(settings=FakeSettings())
    try:
        assert dlg._notes.frameShape() == QFrame.NoFrame
        assert dlg._notes.viewport().autoFillBackground() is False
    finally:
        dlg.deleteLater()


# ---- the header --------------------------------------------------------------

def _label_texts(dlg):
    """What every label in the dialog shows, markup resolved, notes excluded."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocumentFragment
    from PySide6.QtWidgets import QLabel
    return [lab.text() if lab.textFormat() == Qt.PlainText
            else QTextDocumentFragment.fromHtml(lab.text()).toPlainText()
            for lab in dlg.findChildren(QLabel)]


SEVERAL = NOTES + """
## [1.20.2] — 2026-06-10

- An older fix.
"""


@pytest.mark.parametrize("current,kwargs,header", [
    ("1.21.0", {"last_seen": "1.20.1"}, "What's new since 1.20.1"),      # one update, two versions
    ("1.21.0", {"last_seen": "1.20.2", "text": SEVERAL},
     "What's new since 1.20.2"),                                         # several versions
    ("1.21.0", {"last_seen": None}, "Welcome to PyReconstruct"),         # first launch
    ("1.21.0", {"on_demand": True}, "Recent releases"),                  # Help menu
    ("1.21.0", {"last_seen": "1.21.0"}, "Welcome to PyReconstruct"),     # nothing new
    ("1.22.0.dev20261007", {"last_seen": "1.21.0"},
     "What's new since 1.21.0"),                                         # a nightly
    (None, {"on_demand": True}, "Recent releases"),                      # unknown version
])
def test_header_is_one_line_naming_no_version_or_date_of_its_own(
        qapp, current, kwargs, header):
    """The dialog's header is the orienter alone, in the title style.

    The running version and its release date are not in it, nor on any other
    label: each version listed below carries both in its own heading, so the
    header saying them too was the same facts twice.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    kwargs.setdefault("text", NOTES)
    content = F.whats_new_content(current, **kwargs)
    dlg = WhatsNewDialog(None, current, content=content,
                         settings=FakeSettings(), url="https://example.test")
    try:
        assert dlg._header.text() == header
        font = dlg._header.font()
        assert font.bold() is True
        assert font.pointSizeF() > dlg.font().pointSizeF() + 4
        texts = _label_texts(dlg)
        for shown in texts:
            if current:
                assert current not in shown, f"the version is in {shown!r}"
            assert "July 20, 2026" not in shown, f"the date is in {shown!r}"
            assert "Released" not in shown
        # each listed version keeps its own heading with its date
        if kwargs.get("text") == SEVERAL and kwargs.get("last_seen"):
            notes = dlg._notes.toPlainText()
            assert "1.21.0 — July 20, 2026" in notes
            assert "1.20.3 — June 29, 2026" in notes
            assert "1.20.2" not in notes      # older than the last-seen version
    finally:
        dlg.deleteLater()


def test_header_is_the_first_thing_in_the_dialog(qapp):
    """One line above the notes: nothing else sits between it and them."""
    from PySide6.QtWidgets import QLabel
    dlg = _dialog(settings=FakeSettings())
    try:
        dlg.resize(760, 640)
        dlg.show()
        dlg.layout().activate()
        above = [lab for lab in dlg.findChildren(QLabel)
                 if lab.isVisible()
                 and lab.geometry().bottom() < dlg._notes.geometry().top()]
        assert above == [dlg._header]
        assert dlg._header.height() < 2 * dlg._header.fontMetrics().height()
    finally:
        dlg.deleteLater()


# ---- inline code -------------------------------------------------------------

CODE_NOTES = """## [1.21.0] — 2026-07-20

- **Double-click a `.jser` file to open it.** The command line takes the path
  directly: `pyreconstruct series.jser`.
"""


def _code_dialog():
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    content = F.whats_new_content("1.21.0", last_seen="1.20.1", text=CODE_NOTES)
    return WhatsNewDialog(None, "1.21.0", content=content,
                          settings=FakeSettings(), url="https://example.test")


def _runs(dlg):
    """(text, char format, previous fragment's format) for each fragment."""
    out = []
    for block in _blocks(dlg):
        prev = None
        for fragment in _fragments(block):
            out.append((fragment.text(), fragment.charFormat(), prev))
            prev = fragment.charFormat()
    return out


def test_inline_code_matches_the_body_x_height_color_and_weight(qapp):
    """Inline code sits in the body text instead of standing out of it.

    The platform monospace, at the size where its x-height is the body's,
    in the body's color and in the weight of the words around it (bold
    inside a bold claim), with ordinary letter spacing and a faint tint.
    """
    import sys
    from PySide6.QtGui import QFont, QFontMetricsF, QFontDatabase
    from PyReconstruct.modules.gui.dialog.whats_new import (
        CODE_FAMILIES, notes_text_color, blend_toward_text, CODE_TINT_BLEND,
    )
    dlg = _code_dialog()
    try:
        body_font = dlg._notes.document().defaultFont()
        body_x = QFontMetricsF(body_font).xHeight()
        palette = dlg._notes.palette()
        code = [(t, f, p) for t, f, p in _runs(dlg) if f.fontFixedPitch()]
        assert [t for t, _, _ in code] == [".jser", "pyreconstruct series.jser"]
        platform = "linux" if sys.platform.startswith("linux") else sys.platform
        allowed = set(CODE_FAMILIES.get(platform, ())) | {
            QFontDatabase.systemFont(QFontDatabase.FixedFont).family()}
        for text, fmt, prev in code:
            (family,) = fmt.fontFamilies()
            assert family in allowed
            mono = QFont(family)
            mono.setPointSizeF(fmt.fontPointSize())
            assert abs(QFontMetricsF(mono).xHeight() - body_x) < 0.5, text
            assert fmt.foreground().color() == notes_text_color(palette)
            assert fmt.background().color() == blend_toward_text(
                palette, CODE_TINT_BLEND)
            assert fmt.fontWeight() == prev.fontWeight(), text
            assert fmt.fontLetterSpacing() in (0, 100)
        assert code[0][1].fontWeight() == 700      # inside the bold claim
        assert code[1][1].fontWeight() == 400      # in the plain sentence
    finally:
        dlg.deleteLater()


def test_code_tint_is_faint_in_both_themes(qapp):
    """The tint behind code stays close to the background in both themes."""
    import qdarkstyle
    from PyReconstruct.modules.gui.dialog.whats_new import (
        blend_toward_text, CODE_TINT_BLEND,
    )
    app = QApplication.instance()
    previous = app.styleSheet()
    try:
        for sheet in ("", qdarkstyle.load_stylesheet_pyside6()):
            app.setStyleSheet(sheet)
            if not sheet:
                app.setPalette(app.style().standardPalette())
            dlg = _code_dialog()
            try:
                palette = dlg._notes.palette()
                bg = palette.color(QPalette.Active, QPalette.Window)
                tint = blend_toward_text(palette, CODE_TINT_BLEND)
                assert 1.0 < _contrast(tint, bg) < 1.25
            finally:
                dlg.deleteLater()
    finally:
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


# ---- the Close button --------------------------------------------------------

def _dark_sheet():
    import qdarkstyle
    from PyReconstruct.modules.gui.main.main_window import qdark_addon
    return qdarkstyle.load_stylesheet_pyside6() + qdark_addon


def _drawn_close_size(close):
    """The box Close is drawn in: the style's layout item rect when it has
    one (macOS draws a native button inside its widget), else the widget."""
    from PySide6.QtWidgets import QStyle, QStyleOptionButton
    opt = QStyleOptionButton()
    close.initStyleOption(opt)
    drawn = close.style().subElementRect(QStyle.SE_PushButtonLayoutItem, opt, close)
    return drawn.size() if drawn.isValid() else close.size()


def _close_in(theme):
    """Open the dialog under ``theme`` and return Close's drawn size there."""
    app = QApplication.instance()
    app.setStyleSheet(_dark_sheet() if theme == "dark" else "")
    if theme == "light":
        app.setPalette(app.style().standardPalette())
    dlg = _dialog(settings=FakeSettings())
    try:
        dlg.show()
        app.processEvents()
        close = dlg._close
        assert close.font().pointSizeF() == dlg.font().pointSizeF()
        word = close.fontMetrics().horizontalAdvance("Close")
        size = _drawn_close_size(close)
        assert size.width() >= word + 8               # room around the word
        assert size.height() >= close.fontMetrics().height()
        return close.styleSheet(), size
    finally:
        dlg.deleteLater()


def test_close_is_the_same_size_in_both_themes(qapp):
    """Close draws at the same width and height in light and dark.

    Light keeps the native button, untouched. Dark gives it a fixed size
    equal to the box the native button draws in, which on macOS is smaller
    than the native widget.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import native_button_box
    app = QApplication.instance()
    previous = app.styleSheet()
    try:
        light_sheet, light = _close_in("light")
        dark_sheet, dark = _close_in("dark")
        assert light_sheet == ""
        assert dark_sheet != ""
        assert dark == light
        probe = _dialog(settings=FakeSettings())
        assert native_button_box(probe._close) == light
        probe.deleteLater()
    finally:
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


def test_close_follows_a_live_theme_switch(qapp):
    """Switching theme with the dialog open keeps Close the same size."""
    app = QApplication.instance()
    previous = app.styleSheet()
    dlg = None
    try:
        app.setStyleSheet("")
        dlg = _dialog(settings=FakeSettings())
        dlg.show()
        app.processEvents()
        light_widget = dlg._close.size()
        light = _drawn_close_size(dlg._close)
        app.setStyleSheet(_dark_sheet())
        app.processEvents()
        assert dlg._close.styleSheet() != ""
        assert _drawn_close_size(dlg._close) == light
        app.setStyleSheet("")
        app.processEvents()
        assert dlg._close.styleSheet() == ""
        assert dlg._close.sizeHint() == light_widget
        assert _drawn_close_size(dlg._close) == light
    finally:
        if dlg is not None:
            dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


# ---- shortcuts and menu paths ------------------------------------------------

KEY_NOTES = """## [1.21.0] — 2026-07-20

- **Hide the lists with Cmd+Option+S (Ctrl+Alt+S on Windows and Linux).** Shift+K
  picks the scissors (Series ▸ Options ▸ View picks the hover), and View ▸
  Show/hide lists brings them back.
- Read Cmd as Ctrl on Windows and Linux, and View the series as you like.
- In Series ▸ Options ▸ Mouse Tools, uncheck it.
- Double-click a `.jser` file.
"""


def _key_dialog():
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    content = F.whats_new_content("1.21.0", last_seen="1.20.1", text=KEY_NOTES)
    return WhatsNewDialog(None, "1.21.0", content=content,
                          settings=FakeSettings(), url="https://example.test")


def _code_runs(dlg):
    """(text, format) of each inline-code run, adjacent fragments joined."""
    runs = []
    for block in _blocks(dlg):
        last = None
        for fragment in _fragments(block):
            fmt = fragment.charFormat()
            if not fmt.fontFixedPitch():
                last = None
                continue
            if last is not None and last[1].fontWeight() == fmt.fontWeight():
                runs[-1] = (runs[-1][0] + fragment.text(), runs[-1][1])
            else:
                runs.append((fragment.text(), fmt))
            last = runs[-1]
    return runs


def _shown(text):
    """The text as read: no-break spaces as spaces, word joiners dropped."""
    return text.replace("\u00a0", " ").replace("\u2060", "")


def test_shortcuts_and_menu_paths_take_the_inline_code_style(qapp):
    """Plain-text key combos and menu paths render exactly like `.jser`.

    A combo inside the bold claim keeps the claim's bold weight; the
    "on Windows and Linux" words around an alternate combo stay plain; a menu
    path inside parentheses is styled up to its last label and not the
    sentence after it, and a capitalized word before a path stays out of it.
    """
    dlg = _key_dialog()
    try:
        runs = [(_shown(t), f) for t, f in _code_runs(dlg)]
        assert [t for t, _ in runs] == [
            "Cmd+Option+S", "Ctrl+Alt+S", "Shift+K",
            "Series ▸ Options ▸ View", "View ▸ Show/hide lists",
            "Series ▸ Options ▸ Mouse Tools", ".jser",
        ]
        weights = {t: f.fontWeight() for t, f in runs}
        assert weights["Cmd+Option+S"] == 700      # inside the bold claim
        assert weights["Ctrl+Alt+S"] == 700
        assert weights["Shift+K"] == 400
        assert weights["Series ▸ Options ▸ View"] == 400
        jser = dict(runs)[".jser"]
        for text, fmt in runs:
            assert fmt.fontFamilies() == jser.fontFamilies(), text
            assert fmt.fontPointSize() == pytest.approx(jser.fontPointSize()), text
            assert fmt.foreground().color() == jser.foreground().color(), text
            assert fmt.background().color() == jser.background().color(), text
            assert fmt.fontLetterSpacing() == jser.fontLetterSpacing(), text
    finally:
        dlg.deleteLater()


def test_a_sentence_without_a_combo_or_path_stays_plain(qapp):
    """Key names without "+" and a capitalized word are ordinary text."""
    dlg = _key_dialog()
    try:
        block = next(b for b in _blocks(dlg) if "Read Cmd as Ctrl" in b.text())
        assert not any(f.charFormat().fontFixedPitch() for f in _fragments(block))
    finally:
        dlg.deleteLater()


def test_a_combo_never_splits_and_a_path_wraps_only_after_an_arrow(qapp):
    """Laid out narrow, no line starts inside a combo or inside a menu label."""
    from PyReconstruct.modules.gui.dialog.whats_new import KEY_OR_MENU
    dlg = _key_dialog()
    try:
        doc = dlg._notes.document()
        block = next(b for b in _blocks(dlg) if "Shift+K" in b.text())
        text = block.text()
        spans = []
        for fragment in _fragments(block):
            if fragment.charFormat().fontFixedPitch():
                start = fragment.position() - block.position()
                if spans and spans[-1][1] == start:
                    start = spans.pop()[0]
                spans.append((start, start + fragment.length()))
        assert [_shown(text[a:b]) for a, b in spans] == [
            "Cmd+Option+S", "Ctrl+Alt+S", "Shift+K",
            "Series ▸ Options ▸ View", "View ▸ Show/hide lists"]
        for width in range(140, 420, 7):
            doc.setTextWidth(width)
            layout = block.layout()
            starts = [layout.lineAt(i).textStart()
                      for i in range(1, layout.lineCount())]
            for start, end in spans:
                for line_start in starts:
                    if start < line_start < end:
                        assert text[line_start - 2:line_start] == "▸ ", (
                            width, text[start:end], line_start - start)
    finally:
        dlg.deleteLater()


def test_every_multi_word_menu_label_is_a_real_label():
    """Each entry of MENU_LABELS is spelled as the app spells it, or as a
    shipped note names a label since renamed."""
    import re
    from pathlib import Path
    from PyReconstruct.modules.gui.dialog.whats_new import MENU_LABELS
    import PyReconstruct
    root = Path(PyReconstruct.__file__).parent
    source = "".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    notes = re.sub(r"\s+", " ", (root.parent / "WHATS_NEW.md").read_text(
        encoding="utf-8"))
    for label in MENU_LABELS:
        assert f'"{label}' in source or f"\u25b8 {label}" in notes, label

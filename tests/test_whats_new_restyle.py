"""The What's new dialog's restyled notes and its show-after-update checkbox.

The notes browser renders each version as a large bold heading with its date
in the secondary gray, every item as a paragraph that hangs from a dash
marker, and the body in a palette-derived gray that follows the theme. The
footer's "Show changelog after each update" checkbox is the stored popup
preference stated the way round a reader expects: it reads and writes the
inverse of ``WHATSNEW_SUPPRESS_KEY``, the same key the Help menu toggle uses.
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
        assert dlg._show_box.text() == "Show changelog after each update"
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
            "Show changelog after each update"
        ]
        dlg.show()
        buttons[0].click()
        assert not dlg.isVisible()
    finally:
        dlg.deleteLater()


def test_box_sits_left_of_close_on_the_row_below_the_footer(qapp):
    """Checkbox bottom-left, Close bottom-right, both below the byline row."""
    from PySide6.QtWidgets import QPushButton
    dlg = _dialog(settings=FakeSettings())
    try:
        dlg.show()
        dlg.resize(760, 620)
        dlg.layout().activate()
        close = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Close")
        box = dlg._show_box
        assert box.geometry().top() >= dlg._byline.geometry().bottom()
        assert box.geometry().right() < close.geometry().left()
        assert box.geometry().top() < close.geometry().bottom()
        assert close.geometry().top() < box.geometry().bottom()
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


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_close_has_room_around_its_word_in_both_themes(qapp, theme):
    """Close is a full-size button in both themes, not a tight box.

    Light keeps the native button, untouched. Dark gives it 3 px above and
    below and 12 px each side of the word, with a 40 px floor on the word's
    width, which puts it within a few pixels of the light button.
    """
    from PySide6.QtWidgets import QPushButton
    app = QApplication.instance()
    previous = app.styleSheet()
    dlg = None
    try:
        app.setStyleSheet(_dark_sheet() if theme == "dark" else "")
        if theme == "light":
            app.setPalette(app.style().standardPalette())
        dlg = _dialog(settings=FakeSettings())
        dlg.show()
        app.processEvents()
        close = dlg._close
        word = close.fontMetrics().horizontalAdvance("Close")
        line = close.fontMetrics().height()
        if theme == "light":
            assert close.styleSheet() == ""
            plain = QPushButton("Close")
            plain.setDefault(True)
            assert close.size() == plain.sizeHint()
            plain.deleteLater()
        else:
            assert close.width() >= max(word, 40) + 24
            assert close.height() >= line + 6
        assert close.font().pointSizeF() == dlg.font().pointSizeF()
    finally:
        if dlg is not None:
            dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


def test_close_follows_a_live_theme_switch(qapp):
    """Switching theme with the dialog open resizes Close both ways."""
    app = QApplication.instance()
    previous = app.styleSheet()
    dlg = None
    try:
        app.setStyleSheet("")
        dlg = _dialog(settings=FakeSettings())
        dlg.show()
        app.processEvents()
        light = dlg._close.size()
        app.setStyleSheet(_dark_sheet())
        app.processEvents()
        assert dlg._close.styleSheet() != ""
        assert dlg._close.height() >= dlg._close.fontMetrics().height() + 6
        app.setStyleSheet("")
        app.processEvents()
        assert dlg._close.styleSheet() == ""
        assert dlg._close.sizeHint() == light
    finally:
        if dlg is not None:
            dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())

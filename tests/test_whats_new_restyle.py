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


def test_version_headings_are_large_and_bold_with_the_date_secondary(qapp):
    """A version heading is larger than the body and bold; the date after it
    is body-sized, normal weight, in the secondary gray; and a gap separates
    the second version from the first."""
    from PyReconstruct.modules.gui.dialog.whats_new import (
        secondary_text_color, VERSION_GAP,
    )
    dlg = _dialog(settings=FakeSettings())
    try:
        base = dlg._notes.font().pointSizeF()
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


def test_notes_browser_is_flat_on_the_dialog(qapp):
    """No frame, and the viewport shows the dialog background through it."""
    from PySide6.QtWidgets import QFrame
    dlg = _dialog(settings=FakeSettings())
    try:
        assert dlg._notes.frameShape() == QFrame.NoFrame
        assert dlg._notes.viewport().autoFillBackground() is False
    finally:
        dlg.deleteLater()

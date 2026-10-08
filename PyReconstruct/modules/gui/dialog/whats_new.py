"""First-launch "What's new" dialog.

Shows what changed since the user's last-seen version -- on a fresh install or
after an update that may span several versions -- and can be reopened on demand
from Help -> What's new. It is a normal, dismissible, *modeless* dialog: it never
blocks startup or steals focus the way a prompt would.

This is the *only* place the app puts release notes in front of the user
unasked, and it does so once per version. The updater dialog deliberately does
not render them: at that point the notes describe a version the user has not
installed, so showing them there meant the same notes appeared twice around
every update.
"""

import re
import sys
from html import escape

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QCheckBox, QFrame, QStyle, QStyleOptionButton,
)
from PySide6.QtGui import (
    QColor, QPalette, QTextCursor, QTextCharFormat, QTextBlockFormat,
    QFont, QFontDatabase, QFontMetricsF,
)
from PySide6.QtCore import Qt, QSettings, QEvent, QRect

from functools import partial

from PyReconstruct.modules.backend.updater.install_info import current_version_str
from PyReconstruct.modules.gui.main.first_launch import (
    whats_new_due, whats_new_content, github_release_url, WHATSNEW_KEY,
    WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT, whats_new_suppressed,
    ON_DEMAND_CAP, HOMEPAGE_URL, LINKED_NAME,
)

from PyReconstruct.modules.constants.settings_domain import (
    SETTINGS_ORG, SHARED_APP, domain_for,
)
# ORG/APP name the shared store, kept as module names because tests and the
# isolation suite address the store through them. The live QSettings sites
# below resolve through domain_for(): both What's new keys are per app, so
# under the Dev flavor they land in the Dev app's own store, and the stable
# app's popup state is never touched by a nightly.
ORG = SETTINGS_ORG
APP = SHARED_APP


class LinkLabel(QLabel):
    """A rich-text label whose link color survives a live theme change.

    QLabel builds its ``QTextDocument`` when the text is set, and resolves the
    anchor color (``QPalette::Link``) into it at that moment. Plain text keeps
    following the palette at paint time; the anchor does not. So switching theme
    through Help > Theme with this dialog already open leaves every linked word
    in the *previous* theme's blue -- measured at 1.85:1 against the dark
    background, where the same dialog built fresh under that theme renders it at
    3.16:1.

    Re-setting the text rebuilds the document against the current palette. It
    has to go through an empty string on the way: ``QLabel::setText`` returns
    early when the new text equals the old, so assigning the same markup back is
    a no-op -- measured, it leaves the stale color exactly where it was.

    ``PaletteChange`` is the event to catch, and it is the only one needed. It
    arrives on both halves of the app's theme switch: the ``qdark`` branch,
    which only calls ``QApplication.setStyleSheet()``, and the ``default``
    branch, which calls ``setPalette()`` as well.
    """

    def __init__(self, markup, parent=None):
        super().__init__(parent)
        self._markup = markup
        self.setTextFormat(Qt.RichText)
        self.setText(self._styled())

    def _styled(self):
        """The markup to render right now; subclasses may restyle it.

        Called once at construction and again on every ``PaletteChange``, so a
        subclass that derives styling from the palette (``SecondaryLabel``)
        stays current through a live theme switch for free.
        """
        return self._markup

    def changeEvent(self, event):
        # getattr: change events can arrive from inside QLabel.__init__, before
        # _markup is assigned.
        if event.type() == QEvent.Type.PaletteChange and getattr(self, "_markup", None):
            super().setText("")
            super().setText(self._styled())
        super().changeEvent(event)


# How far the secondary color steps from the dialog background toward the
# full text color (0 is the background, invisible; 1 is body text). The
# release date beside each version and the footer line are asides, so they
# stay lighter than the notes, but still clear the 4.5:1 contrast floor in both
# themes: 5.2:1 light (#efefef background), 5.0:1 dark (qdark's #19232d).
SECONDARY_TEXT_BLEND = 0.58

# How far the release-note body text steps from the dialog background toward
# the full text color. The notes are read in bulk, so they take a darker gray
# than the secondary lines above and clear 7:1: 9.6:1 light, 7.5:1 dark. The
# version headings stay in the full text color, so a heading still reads
# darker than the notes under it.
NOTES_TEXT_BLEND = 0.75


def blend_toward_text(palette, fraction):
    """A color ``fraction`` of the way from the dialog background to its text.

    Both endpoints are palette roles (``QPalette::Window`` and ``QPalette::
    Active WindowText``), so the result follows the theme; see
    ``secondary_text_color`` for why these two roles and not the disabled one.
    """
    text = palette.color(QPalette.Active, QPalette.WindowText)
    bg = palette.color(QPalette.Active, QPalette.Window)

    def step(b, t):
        return round(b + fraction * (t - b))

    return QColor(
        step(bg.red(), text.red()),
        step(bg.green(), text.green()),
        step(bg.blue(), text.blue()),
    )


def notes_text_color(palette):
    """The gray the release-note body paints in; see ``NOTES_TEXT_BLEND``."""
    return blend_toward_text(palette, NOTES_TEXT_BLEND)


def secondary_text_color(palette):
    """The color the dialog's secondary lines paint in, derived from the theme.

    The release date and the maintainer byline are secondary to the body text:
    lighter than the body, dark enough to read. The color steps
    ``SECONDARY_TEXT_BLEND`` of the way from the dialog background
    (``QPalette::Window``) toward the full text color (``QPalette::Active
    WindowText``); see the constant for how far and for the paper trail on
    the number.

    Background-to-text, deliberately not disabled-to-text: an earlier blend
    started from ``QPalette::Disabled WindowText``, and on macOS that
    degenerates. Measured on cocoa, the Disabled and Active WindowText roles
    are BOTH #000000 -- the macOS style dims disabled text at paint time, not
    in the palette -- so a dim-to-full blend returns pure black at every
    fraction there, while offscreen/Fusion (#bebebe disabled) renders the
    intended gray and every headless measurement looks fine. Background and
    text are the two roles a theme can never leave equal without being
    unreadable outright.

    Derived from the palette rather than named as a hex so it follows the
    theme: both endpoint roles are theme-supplied, and the qdark stylesheet
    resolves its own colors into the widget palette, so the same blend lands
    right on the dark background too.
    """
    return blend_toward_text(palette, SECONDARY_TEXT_BLEND)


class SecondaryLabel(LinkLabel):
    """A ``LinkLabel`` painted in the dialog's secondary text color.

    The color is written into the markup as an inline span rather than set
    through ``setPalette``, because a per-widget palette loses to the app-level
    qdark stylesheet (measured: the override renders in the stylesheet's normal
    text color, not the palette's). Inline rich-text color wins over both. The
    span is recomputed from the current palette on every ``PaletteChange``
    through ``_styled``, so a live theme switch recolors the line instead of
    stranding it; any anchor inside the markup keeps the ordinary
    ``QPalette::Link`` styling, which the span does not reach into.
    """

    def _styled(self):
        color = secondary_text_color(self.palette()).name()
        return f'<span style="color:{color}">{self._markup}</span>'


# The marker each release-note item hangs from. Qt rich text has no custom
# list marker, so the item is a plain paragraph that starts with this and
# wraps under its own first word (``restyle_notes``).
ITEM_MARKER = "\u2014 "

# How much larger than the dialog's own font the notes are, in points. The
# notes are the one thing here read at length, so they get a little more
# size than the labels around them.
NOTES_SIZE_STEP = 1.5

# Line height of the notes, as a percentage of the font's own: a wrapped item
# reads as one paragraph with air between its lines, not a dense block.
NOTES_LINE_HEIGHT = 150

# Vertical rhythm of the notes, in pixels: between items, above a version
# heading, and above a type heading (New, Improved, Changed, Fixed) within a
# version. These add to the room the line height already leaves under each
# line.
ITEM_GAP = 10
VERSION_GAP = 40
TYPE_GAP = 14

# How much larger than the notes a version heading is, in points. With
# NOTES_SIZE_STEP this stays under the dialog's own title, which remains the
# largest text on screen.
VERSION_HEADING_STEP = 4

# Inline code (`.jser`) in the notes: the platform's own monospace, first
# installed one wins, and the system fixed font after these. Qt's markdown
# reader sets code in the system fixed font at its own size and normal weight,
# which next to the body reads too large and too light, more so inside a bold
# claim. ``restyle_code_runs`` resizes it so its x-height matches the body's
# and gives it the weight of the text around it.
CODE_FAMILIES = {
    "darwin": ("SF Mono", "Menlo", "Monaco"),
    "win32": ("Consolas", "Cascadia Mono", "Courier New"),
    "linux": ("DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono"),
}

# How far the tint behind inline code steps from the background toward the
# text color: just enough to mark the span in either theme.
CODE_TINT_BLEND = 0.07


def code_font_family():
    """The monospace family inline code is set in on this platform."""
    installed = set(QFontDatabase.families())
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    for family in CODE_FAMILIES.get(platform, ()):
        if family in installed:
            return family
    return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()


def code_char_format(base_font, base_pt, weight, color, tint):
    """The character format for one run of inline code in the notes.

    The point size scales ``base_pt`` by the body's x-height over the
    monospace's, so lowercase letters stand as tall in the code as around it.
    """
    family = code_font_family()
    mono = QFont(family)
    mono.setPointSizeF(base_pt)
    mono_x = QFontMetricsF(mono).xHeight()
    body_x = QFontMetricsF(base_font).xHeight()
    fmt = QTextCharFormat()
    fmt.setFontFamilies([family])
    fmt.setFontFixedPitch(True)
    fmt.setFontPointSize(base_pt * body_x / mono_x if mono_x > 0 else base_pt)
    fmt.setFontWeight(weight)
    fmt.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
    fmt.setFontLetterSpacing(100)
    fmt.setForeground(color)
    fmt.setBackground(tint)
    return fmt


def restyle_code_runs(cursor, block, base_font, base_pt, color, tint):
    """Restyle every inline code run in ``block``; see ``code_char_format``.

    Each run takes the weight of the text just before it in the block, which
    is the weight the markdown gave the words it sits among, and it never
    breaks: spaces become no-break spaces and a word joiner follows each "/"
    or "-", so a command such as ``pyreconstruct /path/to/series.jser`` wraps
    as one word instead of splitting across two lines.
    """
    runs = []
    weight = 400
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        fmt = fragment.charFormat()
        if fmt.fontFixedPitch():
            runs.append((fragment.position(), fragment.length(), weight))
        else:
            weight = fmt.fontWeight()
        it += 1
    for start, length, run_weight in runs:
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.KeepAnchor)
        text = "".join(
            "\u00a0" if ch == " " else ch + "\u2060" if ch in "/-" else ch
            for ch in cursor.selectedText())
        cursor.insertText(text, code_char_format(
            base_font, base_pt, run_weight, color, tint))


# Keyboard shortcuts in the notes: one or more modifiers joined by "+" to a
# key, as in Shift+K, Cmd+Option+S or Cmd+comma. The notes write them as plain
# text; ``restyle_key_and_menu_runs`` sets them like inline code.
KEY_COMBO = (
    r"(?<![\w+])(?:(?:Cmd|Ctrl|Option|Alt|Shift)\+)+"
    r"(?:[A-Za-z0-9]+|[,./;'\[\]=\\-])"
)

# Menu labels of more than one word that the notes name, longest first in the
# pattern so "What's new?" wins over "What's new". A label of one word, or of
# capitalized words only ("Mouse Tools"), needs no entry; a lowercase second
# word cannot be told from the sentence going on ("View picks which data")
# without one.
MENU_LABELS = (
    "Show/Hide lists", "Clean up", "Shortcuts list", "Reset window",
    "Search menus", "What's new?", "What's new", "Recolor all objects from palette",
    "View log file", "Color filter", "Set filter...", "Autoseg import colors",
    "Import alignments", "Online resources", "Turn off What's new pop-up",
    # the Help menu toggle's name before 1.23, and the View toggle's before
    # 1.24; older notes still say them
    "Show what's new after updates", "Show/hide lists",
)

# Menu paths in the notes: two or more labels joined by " ▸ ". A label is
# one of MENU_LABELS or a run of capitalized words, except the first, which
# is one word, so a capitalized word before the path ("In Series ▸ Options")
# stays out of it.
_KNOWN_LABEL = (
    "(?:" + "|".join(re.escape(label) for label in
                     sorted(MENU_LABELS, key=len, reverse=True))
    + r")(?!\w)"
)
_WORD = r"[A-Z][\w'’/&-]*"
MENU_PATH = (
    rf"(?<![\w'’])(?:{_KNOWN_LABEL}|{_WORD})"
    rf"(?: \u25b8 (?:{_KNOWN_LABEL}|{_WORD}(?: {_WORD})*))+"
)

KEY_OR_MENU = re.compile(rf"{KEY_COMBO}|{MENU_PATH}")


def unbreakable_key_or_menu(text):
    """Per character of ``text``, what it becomes so the run breaks right.

    Spaces inside a label become no-break spaces, and so does the space before
    each "▸", so a path wraps only after a "▸" and a label never splits. A
    "/" or "-" is followed by a word joiner, since Qt breaks after either
    ("Show/Hide lists" broke at the slash).
    """
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            after_arrow = i > 0 and text[i - 1] == "\u25b8"
            out.append(" " if after_arrow else "\u00a0")
        elif ch in "/-":
            out.append(ch + "\u2060")
        else:
            out.append(ch)
    return out


def restyle_key_and_menu_runs(cursor, block, base_font, base_pt, color, tint):
    """Set the plain-text shortcuts and menu paths in ``block`` like inline code.

    Matches ``KEY_OR_MENU`` and gives each match the format
    ``code_char_format`` gives a backtick run, in the weight of the text it
    sits in, so one inside a bold claim stays bold. A match that touches
    inline code or a link is left alone. Runs after ``restyle_code_runs``,
    which would otherwise take these runs for code and rejoin a path's
    breakable spaces.
    """
    origin = block.position()
    pieces = []
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        pieces.append((fragment.position() - origin, fragment.length(),
                       fragment.charFormat()))
        it += 1
    # Back to front: a word joiner lengthens the text, and this way it only
    # moves positions already done.
    matches = list(KEY_OR_MENU.finditer(block.text()))
    for match in reversed(matches):
        start, end = match.span()
        touched = [(pos, length, fmt) for pos, length, fmt in pieces
                   if pos < end and pos + length > start]
        if any(fmt.fontFixedPitch() or fmt.isAnchor() for _, _, fmt in touched):
            continue
        styled = unbreakable_key_or_menu(match.group())
        for pos, length, fmt in reversed(touched):
            lo, hi = max(pos, start), min(pos + length, end)
            cursor.setPosition(origin + lo)
            cursor.setPosition(origin + hi, QTextCursor.KeepAnchor)
            cursor.insertText("".join(styled[lo - start:hi - start]),
                              code_char_format(base_font, base_pt,
                                               fmt.fontWeight(), color, tint))


def restyle_notes(doc, palette):
    """Restyle a markdown-built notes document in place.

    ``setMarkdown`` has already parsed the notes; this walks the blocks and
    sets what the markdown dialect cannot say:

    * a level-3 heading, one per version, is large and bold in the full text
      color, with the `` — date`` after the version in the secondary gray at
      body size, and a gap above it that separates one version from the next;
    * a level-4 heading, one per change type, is bold at body size;
    * every list item leaves its list and becomes a paragraph that starts with
      ``ITEM_MARKER`` and hangs: the left margin is the marker's width and the
      first line is pulled back by the same amount, so a wrapped item lines
      up under its own first word, not under the marker;
    * every non-heading paragraph, items included, takes
      ``NOTES_LINE_HEIGHT`` and paints in ``notes_text_color``;
    * inline code inside those paragraphs is set by ``restyle_code_runs``:
      the platform monospace, the body's x-height, color and weight, on a
      faint tint; plain-text shortcuts and menu paths take the same style
      from ``restyle_key_and_menu_runs``.

    Sizes are relative to the document's default font, which
    ``NotesBrowser`` sets ``NOTES_SIZE_STEP`` above the dialog's own.

    Colors are written into the character formats rather than set on the
    widget, for the reason ``SecondaryLabel`` gives: an inline color is the
    one thing that wins over the app-level dark stylesheet.
    """
    body = notes_text_color(palette)
    secondary = secondary_text_color(palette)
    code_tint = blend_toward_text(palette, CODE_TINT_BLEND)
    base_font = doc.defaultFont()
    # a font set in pixels reports no point size; size the headings from the
    # metrics then, so they still grow instead of collapsing to 4pt
    base_pt = base_font.pointSizeF()
    if base_pt <= 0:
        base_pt = QFontMetricsF(base_font).height() * 0.75
    hang = QFontMetricsF(base_font).horizontalAdvance(ITEM_MARKER)

    body_fmt = QTextCharFormat()
    body_fmt.setForeground(body)

    cursor = QTextCursor(doc)
    cursor.beginEditBlock()
    first_version = True
    block = doc.begin()
    while block.isValid():
        bfmt = block.blockFormat()
        level = bfmt.headingLevel()
        cursor.setPosition(block.position())
        # Headings get a whole new character format rather than a merge: the
        # markdown parser sizes them through FontSizeAdjustment, which Qt
        # applies over any point size merged in, so a merged size would be
        # ignored and the heading would stay at the dialect's own step.
        if level == 3:
            heading_fmt = QTextCharFormat()
            heading_fmt.setFont(base_font)
            heading_fmt.setFontPointSize(base_pt + VERSION_HEADING_STEP)
            heading_fmt.setFontWeight(700)
            cursor.setPosition(block.position() + block.length() - 1,
                               QTextCursor.KeepAnchor)
            cursor.setCharFormat(heading_fmt)
            # the date after the version: body size, normal weight, secondary
            text = block.text()
            cut = text.find(" \u2014 ")
            if cut >= 0:
                date_fmt = QTextCharFormat()
                date_fmt.setFont(base_font)
                date_fmt.setFontPointSize(base_pt)
                date_fmt.setFontWeight(400)
                date_fmt.setForeground(secondary)
                cursor.setPosition(block.position() + cut)
                cursor.setPosition(block.position() + len(text),
                                   QTextCursor.KeepAnchor)
                cursor.setCharFormat(date_fmt)
            bfmt.setTopMargin(0 if first_version else VERSION_GAP)
            bfmt.setBottomMargin(8)
            first_version = False
            cursor.setPosition(block.position())
            cursor.setBlockFormat(bfmt)
        elif level == 4:
            type_fmt = QTextCharFormat()
            type_fmt.setFont(base_font)
            type_fmt.setFontPointSize(base_pt)
            type_fmt.setFontWeight(700)
            cursor.setPosition(block.position() + block.length() - 1,
                               QTextCursor.KeepAnchor)
            cursor.setCharFormat(type_fmt)
            bfmt.setTopMargin(TYPE_GAP)
            bfmt.setBottomMargin(6)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(bfmt)
        else:
            cursor.setPosition(block.position() + block.length() - 1,
                               QTextCursor.KeepAnchor)
            cursor.mergeCharFormat(body_fmt)
            restyle_code_runs(cursor, block, base_font, base_pt, body, code_tint)
            restyle_key_and_menu_runs(cursor, block, base_font, base_pt, body,
                                      code_tint)
            cursor.setPosition(block.position())
            text_list = block.textList()
            if text_list is not None:
                text_list.remove(block)
                bfmt = block.blockFormat()
                bfmt.setIndent(0)
                bfmt.setLeftMargin(hang)
                bfmt.setTextIndent(-hang)
                cursor.setBlockFormat(bfmt)
                cursor.insertText(ITEM_MARKER, body_fmt)
                bfmt = block.blockFormat()
            bfmt.setTopMargin(0)
            bfmt.setBottomMargin(ITEM_GAP)
            bfmt.setLineHeight(NOTES_LINE_HEIGHT,
                               QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(bfmt)
        block = block.next()
    cursor.endEditBlock()


class NotesBrowser(QTextBrowser):
    """A read-only browser that renders release-note markdown, restyled.

    Keeps the markdown so a ``PaletteChange`` can rebuild the document against
    the new palette: the body gray and the date gray are inline colors
    computed from the palette at render time (see ``restyle_notes``), and
    switching theme through Help > Theme with the dialog open would otherwise
    leave them in the previous theme's colors, the same stale-color trap
    ``LinkLabel`` closes for the anchors. The scroll position is kept across
    the rebuild.
    """

    def __init__(self, markdown_text, parent=None):
        super().__init__(parent)
        self._markdown = markdown_text
        self.setOpenExternalLinks(True)
        # One flat surface with the dialog: no frame, and the viewport shows
        # the dialog background through it instead of painting its own. The
        # stylesheet line is for the dark theme, whose app-level sheet draws
        # a border on every text edit; a widget's own sheet outranks the
        # app's. It says nothing else on purpose: a ``background:
        # transparent`` rule here resolves the widget palette's Window and
        # WindowText to black, which the grays below are blended from.
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("NotesBrowser { border: none; }")
        self.document().setDocumentMargin(2)
        self.render()

    def render(self):
        """Rebuild the document from the markdown against the current palette."""
        scroll = self.verticalScrollBar().value()
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() + NOTES_SIZE_STEP)
        else:
            # a font set in pixels: the same step, at 4 px to 3 pt
            font.setPixelSize(font.pixelSize() + round(NOTES_SIZE_STEP * 4 / 3))
        self.document().setDefaultFont(font)
        try:
            self.setMarkdown(self._markdown)
            restyle_notes(self.document(), self.palette())
        except Exception:
            self.setPlainText(self._markdown)
        self.verticalScrollBar().setValue(scroll)

    def changeEvent(self, event):
        # getattr: change events can arrive from inside QTextBrowser.__init__,
        # before _markdown is assigned.
        if event.type() == QEvent.Type.PaletteChange and getattr(self, "_markdown", None):
            self.render()
        super().changeEvent(event)


def make_notes_browser(markdown_text, min_height=180):
    """Build a ``NotesBrowser`` for release-note markdown.

    Falls back to plain text if the markdown can't be rendered.
    """
    # Asterisks, not underscores: Qt's GitHub markdown dialect renders
    # _underscore emphasis_ as underline, which reads as a broken link.
    text = markdown_text or "*No release notes were published.*"
    browser = NotesBrowser(text)
    browser.setMinimumHeight(min_height)
    return browser


# The dark theme's app stylesheet gives every push button 2 px of padding and
# no minimum width, so Close drew as a tight box around its word, a different
# size from the light theme's native button. While the app has a stylesheet,
# Close takes this sheet (no padding, so the word fits the shorter box) and a
# fixed size equal to the box the native button draws in; see
# ``native_button_box``. Under the light theme the button keeps no sheet and
# no fixed size, and draws natively.
DARK_BUTTON_SHEET = "QPushButton { padding: 0px; }"

# Qt's QWIDGETSIZE_MAX, which PySide does not export: the no-limit maximum.
QWIDGETSIZE_MAX = (1 << 24) - 1


def native_button_box(button):
    """The size of the box the native style draws ``button`` in.

    Mirrors ``QPushButton.sizeHint`` for a text-only button, asked of the
    application style with no widget. With an app stylesheet set, that style
    has no widget to match rules against and answers as the native style
    underneath, so this is the light theme's button whichever theme is on.
    The visible box can be smaller than the widget: macOS draws a 64 x 32
    widget as a 64 x 20 bezel, which ``SE_PushButtonLayoutItem`` reports.
    Styles that draw the whole widget leave that rect empty.
    """
    style = QApplication.style()
    opt = QStyleOptionButton()
    button.initStyleOption(opt)
    text = button.fontMetrics().size(Qt.TextShowMnemonic, button.text())
    opt.rect = QRect(0, 0, text.width(), text.height())
    hint = style.sizeFromContents(QStyle.CT_PushButton, opt, text, None)
    opt.rect = QRect(0, 0, hint.width(), hint.height())
    drawn = style.subElementRect(QStyle.SE_PushButtonLayoutItem, opt, None)
    return drawn.size() if drawn.isValid() else hint


class WhatsNewDialog(QDialog):
    """A dismissible, modeless summary of what changed since the last-seen version."""

    def __init__(self, parent, version, last_seen=None, content=None, url=None,
                 settings=None):
        super().__init__(parent)
        self._version = version
        # Where the "Show this changelog window after each update?" checkbox
        # reads and writes its preference; injectable for headless testing.
        # None means the real store, built once the footer needs it below.
        self._settings = settings
        if content is None:
            content = whats_new_content(version, last_seen)
        if url is None:
            # The releases INDEX, not this version's tag: the dialog already
            # renders this version's notes, so the link's job is everything
            # else -- every shipped version's notes in one place (his ask,
            # 2026-08-25). The truncation line in a capped body points at the
            # same landing.
            url = github_release_url()

        self.setWindowTitle(
            f"What's new in PyReconstruct {version}" if version
            else "What's new in PyReconstruct"
        )
        # 700 minimum width, up from the 540 the dialog opened at when the
        # byline and the release-notes link stacked. At 700 the one-line byline
        # and Close fit side by side, so the extra room is about how much
        # of a release note line fits unwrapped. The height increase lives on the notes
        # browser below, the one widget that should absorb extra space; no
        # other geometry is set, so the dialog keeps sizing itself from its
        # contents.
        self.setMinimumWidth(700)
        self.setModal(False)  # modeless: does not block the app

        lay = QVBoxLayout(self)

        # One header line, the orienter: "What's new since 1.22.1", "Welcome to
        # PyReconstruct" or "Recent releases". It names no version or date of
        # its own, because every version listed below carries both in its own
        # heading. Plain text: the last-seen version comes from the settings
        # store, not from this code.
        self._header = QLabel(content["orienter"])
        self._header.setTextFormat(Qt.PlainText)
        hf = self._header.font()
        hf.setBold(True)
        hf.setPointSize(18 if hf.pointSize() <= 0 else hf.pointSize() + 6)
        self._header.setFont(hf)
        lay.addWidget(self._header)

        # The notes browser renders the release notes and nothing else. The
        # maintainer provenance line used to be appended to the end of this
        # markdown, below a rule, which put it inside the scroll: on a release
        # with more than a screenful of notes -- the normal case -- a reader had
        # to scroll to the bottom to find out who maintains this build, and most
        # never did. It now lives in the footer below the browser (see
        # below), so it is on screen from the moment the dialog opens.
        #
        # 320 minimum height, up from 260: the whole of the dialog's height
        # bump (about 13% on the dialog, 451px to 511px at the default size,
        # offscreen metrics) lands here, because the notes are the one thing
        # worth more room. The browser is the layout's only vertically
        # expanding widget, so user resizes land here too, and the dialog
        # still fits a 13 inch laptop screen with room to spare.
        self._notes = make_notes_browser(content["body"], min_height=320)
        lay.addWidget(self._notes)

        # The provenance line itself: italic, in the same secondary style as
        # the release date above, and a jump link to the project home page. The
        # italic is the aside register the markdown `_..._` gave it inside the
        # notes, and it is kept. The color is the shared secondary one rather
        # than either extreme this line has been at: the disabled-palette
        # dimming it first landed with reads as switched-off (about 1.6:1
        # against the dialog background), and the full text color it briefly
        # took instead made an aside compete with the notes. The derived blend
        # keeps it clearly secondary while a lab that needs to report an issue
        # to the right person can still read it comfortably.
        #
        # Exactly one word of it is a link: the project name, pointing at the
        # home page. That word takes the ordinary link styling -- blue and
        # underlined -- and the rest of the sentence stays plain italic text.
        # Only the word is a click target; the surrounding words are not.
        #
        # The whole line was briefly the anchor, styled to look like ordinary
        # text so as not to stack two link-colored rows. Linking just the name
        # gets the same restraint without the deception: one obvious, ordinary
        # link instead of a whole sentence that was secretly clickable, so it
        # needs neither a color override nor the pointing-hand cursor and
        # tooltip that were standing in for the missing affordance. It is also
        # theme-proof for free -- QPalette::Link is whatever the active theme
        # says it is, resolved at paint, rather than a color this code samples
        # at construction and gets wrong under the dark theme.
        #
        # `escape()` runs before the split, so the anchor is spliced into
        # already-escaped text and the sentence can never inject markup. The
        # split is `partition`, which takes the FIRST occurrence: this byline
        # contains the name exactly once, and if it ever contained none the
        # partition yields empty match/tail and the line renders as plain text
        # with no anchor at all rather than raising.
        #
        # The byline comes from the builder as its own field and is the same on
        # every framing (update, welcome, on-demand, generic fallback);
        # rendering it here, once, is the only place it appears, so it can never
        # double up with the notes above it. Some framings carry no byline, and
        # then no widget is added at all.
        #
        # The footer is two rows. The upper one, right under the notes, holds
        # the "All release notes" link on the left and the "Show this
        # changelog window after each update?" checkbox on the right; the lower one
        # holds the byline on the left and Close on the right, the default
        # (Enter) button in the ordinary bottom-right spot. When the byline is
        # absent a stretch keeps Close on the right, where it always is.
        #
        # The checkbox is the popup preference stated the way round a reader
        # expects (checked means it shows), and it is the inverse of the
        # stored ``WHATSNEW_SUPPRESS_KEY``, the same key the Help menu toggle
        # reads and writes, so either can undo the other. Each toggle writes
        # at once; nothing waits for Close. The box opens on the stored state,
        # so the dialog reads the store here.
        options = QHBoxLayout()
        self._show_box = QCheckBox("Show this changelog window after each update?")
        self._show_box.setChecked(not whats_new_suppressed(
            self._store().value(WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT)
        ))
        self._show_box.toggled.connect(self.setShowAfterUpdate)

        # Same LinkLabel as the byline: this label has always had the same
        # stale-anchor-color behavior on a live theme switch, and fixing one
        # anchor in the dialog while leaving the other stale would show.
        link = LinkLabel(f'<a href="{url}">All release notes on GitHub ↗</a>')
        link.setOpenExternalLinks(True)
        options.addWidget(link)
        options.addStretch(1)
        options.addWidget(self._show_box)
        lay.addLayout(options)

        row = QHBoxLayout()
        byline = content.get("byline")
        if byline:
            before, name, after = escape(byline).partition(LINKED_NAME)
            markup = (
                f'{before}<a href="{HOMEPAGE_URL}">{name}</a>{after}' if name
                else before
            )
            # One line, never wrapped: the label's minimum width is the whole
            # sentence, so the row cannot squeeze it onto a second line.
            self._byline = SecondaryLabel(markup)
            bf = self._byline.font()
            bf.setItalic(True)
            self._byline.setFont(bf)
            self._byline.setOpenExternalLinks(True)
            self._byline.setWordWrap(False)
            row.addWidget(self._byline, 1)
        else:
            self._byline = None
            row.addStretch(1)
        self._close = QPushButton("Close")
        self._close.setDefault(True)
        self._close.clicked.connect(self.accept)
        self._fit_buttons()
        row.addWidget(self._close)
        lay.addLayout(row)

    def _fit_buttons(self):
        """Set or clear Close's dark-theme sheet and size; see ``DARK_BUTTON_SHEET``."""
        app = QApplication.instance()
        sheet = DARK_BUTTON_SHEET if app is not None and app.styleSheet() else ""
        if self._close.styleSheet() != sheet:
            self._close.setStyleSheet(sheet)
        if sheet:
            self._close.setFixedSize(native_button_box(self._close))
        else:
            self._close.setMinimumSize(0, 0)
            self._close.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

    def changeEvent(self, event):
        # The theme switch sets or clears the app stylesheet with this dialog
        # open; follow it. getattr: change events can arrive from inside
        # QDialog.__init__, before the button exists.
        if (event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange)
                and getattr(self, "_close", None) is not None):
            self._fit_buttons()
        super().changeEvent(event)

    def _store(self):
        """The settings store the checkbox reads and writes."""
        if self._settings is None:
            self._settings = QSettings(*domain_for(WHATSNEW_SUPPRESS_KEY))
        return self._settings

    def setShowAfterUpdate(self, checked):
        """Persist the checkbox: checked means the popup shows after an update.

        Writes ``WHATSNEW_SUPPRESS_KEY`` as the inverse of ``checked`` and
        nothing else: the once-per-version record is left alone, so a user who
        switches the popup back on picks the ordinary rules up where they
        stood, a version bump missed while it was off included.
        """
        self._store().setValue(WHATSNEW_SUPPRESS_KEY, not checked)


def _default_show(parent, version, last_seen=None, content=None, settings=None):
    """Construct and show the dialog modelessly, transiently."""
    dialog = WhatsNewDialog(parent, version, last_seen=last_seen, content=content,
                            settings=settings)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    if parent is not None:
        # Hold a reference so the modeless dialog isn't garbage-collected before
        # it shows, and drop it once dismissed so nothing lingers on the window.
        parent._whatsnew_dialog = dialog
        dialog.finished.connect(lambda *_: setattr(parent, "_whatsnew_dialog", None))
    dialog.show()
    return dialog


def maybe_show_whats_new(parent, settings=None, current=None, show=None,
                         key=WHATSNEW_KEY):
    """Show the What's-new dialog once per version; record the version seen.

    The pure gates live in ``whats_new_suppressed`` and ``whats_new_due``; this
    wires them to QSettings and the dialog. The stored last-seen version is
    threaded into the builder so the dialog can summarise everything missed
    since then. ``settings`` / ``current`` / ``show`` are injectable for
    headless testing. Returns True if shown.

    The suppression check comes first and returns without writing anything:
    a switched-off popup beats a pending version bump, and leaving the last-seen
    record where it stood is what lets the Help-menu toggle hand the ordinary
    once-per-version rules back intact, pending bump included.
    """
    if settings is None:
        settings = QSettings(*domain_for(WHATSNEW_SUPPRESS_KEY, key))
    if current is None:
        current = current_version_str()
    if whats_new_suppressed(settings.value(WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT)):
        return False
    stored = settings.value(key)
    if not whats_new_due(stored, current):
        return False
    if show is None:
        # the default dialog gets this same store, so its "Show changelog after
        # each update" box writes where this gate reads; an injected show is a test seam
        # with the historical (parent, version, last_seen) signature
        show = partial(_default_show, settings=settings)
    show(parent, current, stored)
    settings.setValue(key, current)
    return True


def show_whats_new(parent, current=None, show=None):
    """Show the What's-new dialog on demand (Help -> What's new).

    Unlike ``maybe_show_whats_new`` there is no once-per-version gate and no
    suppression (a menu click is an explicit request, not a popup), and the
    stored last-seen version is neither consulted nor updated:
    the dialog always opens on the running version's notes rather than a
    fresh-install welcome.
    Earlier releases are reached through the truncation line and the "Full
    release notes on GitHub" link rather than being listed in full; see
    ``ON_DEMAND_CAP`` for why this path is capped tighter than the post-update
    one. ``current`` / ``show`` are injectable for headless testing. Returns the
    dialog.
    """
    if current is None:
        current = current_version_str()
    content = whats_new_content(current, on_demand=True, cap=ON_DEMAND_CAP)
    return (show or _default_show)(parent, current, content=content)

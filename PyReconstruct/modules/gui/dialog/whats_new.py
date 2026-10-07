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

from html import escape

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QCheckBox, QFrame,
)
from PySide6.QtGui import (
    QColor, QPalette, QTextCursor, QTextCharFormat, QTextBlockFormat,
    QFontMetricsF,
)
from PySide6.QtCore import Qt, QSettings, QEvent

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
# release date, "Released" and the footer line are asides, so they stay
# lighter than the notes, but still clear the 4.5:1 contrast floor in both
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
      ``NOTES_LINE_HEIGHT`` and paints in ``notes_text_color``.

    Sizes are relative to the document's default font, which
    ``NotesBrowser`` sets ``NOTES_SIZE_STEP`` above the dialog's own.

    Colors are written into the character formats rather than set on the
    widget, for the reason ``SecondaryLabel`` gives: an inline color is the
    one thing that wins over the app-level dark stylesheet.
    """
    body = notes_text_color(palette)
    secondary = secondary_text_color(palette)
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


class WhatsNewDialog(QDialog):
    """A dismissible, modeless summary of what changed since the last-seen version."""

    def __init__(self, parent, version, last_seen=None, content=None, url=None,
                 settings=None):
        super().__init__(parent)
        self._version = version
        # Where the "Show changelog after each update" checkbox reads and
        # writes its preference; injectable for headless testing. None means
        # the real store, built once the footer needs it below.
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
        # footer text and the release-notes link stacked. The width does not
        # shape the footer: the provenance line is one short line at every
        # width, so the extra room is purely about how much of a release note
        # line fits unwrapped. The height increase lives on the notes browser
        # below, the one widget that should absorb extra space; no other
        # geometry is set, so the dialog keeps sizing itself from its
        # contents.
        self.setMinimumWidth(700)
        self.setModal(False)  # modeless: does not block the app

        lay = QVBoxLayout(self)

        # prominent version header, with the release date beneath it -- omitted
        # when the running version is unknown (never render "None"; the
        # orienter below then leads the dialog)
        if content["version"]:
            title = QLabel(f"PyReconstruct {content['version']}")
            tf = title.font()
            tf.setBold(True)
            tf.setPointSize(18 if tf.pointSize() <= 0 else tf.pointSize() + 6)
            title.setFont(tf)
            lay.addWidget(title)

        # The release date is secondary to the version above it: italic, in the
        # derived secondary color rather than dimmed by `setEnabled(False)` as
        # it first was. The disabled rendering measured about 1.6:1 against
        # the dialog background (offscreen/Fusion), and the label stays
        # enabled so it paints from the Active group like everything else.
        # Escaped: the date string comes from parsed release notes and this
        # label renders rich text.
        if content.get("date"):
            released = SecondaryLabel(escape(f"Released {content['date']}"))
            rf = released.font()
            rf.setItalic(True)
            released.setFont(rf)
            lay.addWidget(released)

        orienter = QLabel(content["orienter"])
        of = orienter.font()
        of.setItalic(True)
        orienter.setFont(of)
        lay.addWidget(orienter)

        # The notes browser renders the release notes and nothing else. The
        # maintainer provenance line used to be appended to the end of this
        # markdown, below a rule, which put it inside the scroll: on a release
        # with more than a screenful of notes -- the normal case -- a reader had
        # to scroll to the bottom to find out who maintains this build, and most
        # never did. It now lives in the footer row below the browser (see
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
        # It shares one footer row with the "All release notes" link: byline
        # on the left, link on the right, action buttons on their own row
        # below. Stacked, the two small-text lines read as one block and cost a
        # row of vertical space each; side by side they are two footer items
        # with distinct jobs. When the byline is absent a stretch keeps the
        # link on the right, where it always is.
        footer = QHBoxLayout()
        byline = content.get("byline")
        if byline:
            before, name, after = escape(byline).partition(LINKED_NAME)
            markup = (
                f'{before}<a href="{HOMEPAGE_URL}">{name}</a>{after}' if name
                else before
            )
            # Rendered as it is, on one line: the sentence is short enough to
            # fit the footer at the dialog's minimum width, so no explicit
            # break is added.
            self._byline = SecondaryLabel(markup)
            bf = self._byline.font()
            bf.setItalic(True)
            self._byline.setFont(bf)
            self._byline.setOpenExternalLinks(True)
            self._byline.setWordWrap(True)
            footer.addWidget(self._byline, 1)
        else:
            self._byline = None
            footer.addStretch(1)

        # Same LinkLabel as the byline: this label has always had the same
        # stale-anchor-color behavior on a live theme switch, and fixing one
        # anchor in the dialog while leaving the other stale would show.
        # AlignTop: should the provenance line ever wrap, the link stays level
        # with its first line rather than floating mid-row.
        link = LinkLabel(f'<a href="{url}">All release notes on GitHub ↗</a>')
        link.setOpenExternalLinks(True)
        footer.addWidget(link, 0, Qt.AlignTop)
        lay.addLayout(footer)

        # The last row: a "Show changelog after each update" checkbox on the
        # left and one Close button on the right, the default (Enter) button
        # in the ordinary rightmost spot. The checkbox is the popup preference
        # stated the way round a reader expects (checked means it shows), and
        # it is the inverse of the stored ``WHATSNEW_SUPPRESS_KEY``, the same
        # key the Help menu toggle reads and writes, so either can undo the
        # other. Each toggle writes at once; nothing waits for Close. The box
        # opens on the stored state, so the dialog reads the store here.
        row = QHBoxLayout()
        self._show_box = QCheckBox("Show changelog after each update")
        self._show_box.setChecked(not whats_new_suppressed(
            self._store().value(WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT)
        ))
        self._show_box.toggled.connect(self.setShowAfterUpdate)
        row.addWidget(self._show_box)
        row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

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

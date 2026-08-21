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
)
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtCore import Qt, QSettings, QEvent

from functools import partial

from PyReconstruct.modules.backend.updater.install_info import current_version_str
from PyReconstruct.modules.gui.main.first_launch import (
    whats_new_due, whats_new_content, github_release_url, WHATSNEW_KEY,
    WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT, whats_new_suppressed,
    ON_DEMAND_CAP, HOMEPAGE_URL, LINKED_NAME,
)

ORG, APP = "KHLab", "PyReconstruct"


def _space_after_headings(browser, extra=10):
    """Add breathing room below markdown headings in a notes browser.

    Qt's ``setMarkdown`` ignores the document default stylesheet, so we walk the
    blocks and bump the bottom margin on heading blocks instead. Applies to
    whatever headings the notes carry.
    """
    doc = browser.document()
    cursor = QTextCursor(doc)
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        if fmt.headingLevel() > 0:
            fmt.setBottomMargin(fmt.bottomMargin() + extra)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(fmt)
        block = block.next()


class LinkLabel(QLabel):
    """A rich-text label whose link colour survives a live theme change.

    QLabel builds its ``QTextDocument`` when the text is set, and resolves the
    anchor colour (``QPalette::Link``) into it at that moment. Plain text keeps
    following the palette at paint time; the anchor does not. So switching theme
    through Help > Theme with this dialog already open leaves every linked word
    in the *previous* theme's blue -- measured at 1.85:1 against the dark
    background, where the same dialog built fresh under that theme renders it at
    3.16:1.

    Re-setting the text rebuilds the document against the current palette. It
    has to go through an empty string on the way: ``QLabel::setText`` returns
    early when the new text equals the old, so assigning the same markup back is
    a no-op -- measured, it leaves the stale colour exactly where it was.

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
# full text color (0 is the background, invisible; 1 is body text). Dusten
# wants these lines light: "i wanted a lighter gray that was slightly less
# light than the original release date color that was too white." The number
# is his, chosen 2026-08-13 from a rendered ladder of candidates with the
# measured contrast printed beside each: 0.55, the smallest step clearing
# the 4.5:1 floor, still read as too dark to him, and he picked 0.34, about
# 2.3:1 on the light backgrounds (#9c9c9c on cocoa's #ececec). That is a
# deliberate lowering of the legibility floor for these two SECONDARY lines
# only: the pixel tests now hold them above the old disabled rendering's
# 1.6:1, which was reported unreadable, rather than above 4.5:1, and the
# body text's own contrast is untouched. Raising this back toward
# legible-everywhere is one number, but it is his to raise.
SECONDARY_TEXT_BLEND = 0.34


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
    text = palette.color(QPalette.Active, QPalette.WindowText)
    bg = palette.color(QPalette.Active, QPalette.Window)

    def step(b, t):
        return round(b + SECONDARY_TEXT_BLEND * (t - b))

    return QColor(
        step(bg.red(), text.red()),
        step(bg.green(), text.green()),
        step(bg.blue(), text.blue()),
    )


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


def make_notes_browser(markdown_text, min_height=180):
    """Build a read-only ``QTextBrowser`` that renders release-note markdown.

    Falls back to plain text if the markdown can't be rendered.
    """
    text = markdown_text or "_No release notes were published._"
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    try:
        browser.setMarkdown(text)
        _space_after_headings(browser)
    except Exception:
        browser.setPlainText(text)
    browser.setMinimumHeight(min_height)
    return browser


class WhatsNewDialog(QDialog):
    """A dismissible, modeless summary of what changed since the last-seen version."""

    def __init__(self, parent, version, last_seen=None, content=None, url=None,
                 settings=None):
        super().__init__(parent)
        self._version = version
        # Where "Don't show again" persists its preference; injectable for
        # headless testing. None defers building the real store to the click,
        # so constructing the dialog alone never touches QSettings.
        self._settings = settings
        if content is None:
            content = whats_new_content(version, last_seen)
        if url is None:
            url = github_release_url(version)

        self.setWindowTitle(
            f"What's new in PyReconstruct {version}" if version
            else "What's new in PyReconstruct"
        )
        # 700 minimum width, up from the 540 the dialog opened at when the
        # byline and the release-notes link stacked; click-tested and approved
        # at this size. The width does not shape the footer: the byline breaks
        # into its two lines explicitly (see the footer below), the same at
        # every width, so the extra room is purely about how much of a release
        # note line fits unwrapped. The height increase lives on the notes
        # browser below, the one widget that should absorb extra space; no
        # other geometry is set, so the dialog keeps sizing itself from its
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
        # text so as not to stack two link-coloured rows. Linking just the name
        # gets the same restraint without the deception: one obvious, ordinary
        # link instead of a whole sentence that was secretly clickable, so it
        # needs neither a colour override nor the pointing-hand cursor and
        # tooltip that were standing in for the missing affordance. It is also
        # theme-proof for free -- QPalette::Link is whatever the active theme
        # says it is, resolved at paint, rather than a colour this code samples
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
        # It shares one footer row with the "Full release notes" link: byline
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
            # Rendered as two lines, broken at the comma -- "An independent
            # build of PyReconstruct," over "maintained by Dusten Hubbard." --
            # matching the approved mockup. The break is an explicit <br/> so
            # the shape is the same at every window width rather than wrap
            # luck. It is a display concern of this dialog alone, which is why
            # MAINTAINER_BYLINE itself stays one string: the GitHub release
            # footer renders the same sentence inline. A byline without a
            # comma-space renders unchanged, on one line.
            self._byline = SecondaryLabel(markup.replace(", ", ",<br/>", 1))
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
        # stale-anchor-colour behaviour on a live theme switch, and fixing one
        # anchor in the dialog while leaving the other stale would show.
        # AlignTop: the byline renders as two lines (see above), and the link
        # stays level with the byline's first line rather than floating
        # mid-row.
        link = LinkLabel(f'<a href="{url}">Full release notes on GitHub ↗</a>')
        link.setOpenExternalLinks(True)
        footer.addWidget(link, 0, Qt.AlignTop)
        lay.addLayout(footer)

        # "Don't show again" sits left of "Got it", which keeps the default
        # (Enter) button in the ordinary rightmost spot: dismissing this once
        # stays the one-keystroke action, switching it off for good takes a
        # deliberate click. The preference it writes is the same one the Help
        # menu toggle reads and writes, so either can undo the other.
        row = QHBoxLayout()
        row.addStretch(1)
        dont_show_btn = QPushButton("Don't show again")
        dont_show_btn.clicked.connect(self.dontShowAgain)
        row.addWidget(dont_show_btn)
        close_btn = QPushButton("Got it")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

    def dontShowAgain(self):
        """Persist the never-show preference, then close like "Got it".

        Writes ``WHATSNEW_SUPPRESS_KEY`` and nothing else: the once-per-version
        record is left alone, so a user who later re-enables the popup from the
        Help menu picks the ordinary rules back up where they stood.
        """
        settings = self._settings if self._settings is not None else QSettings(ORG, APP)
        settings.setValue(WHATSNEW_SUPPRESS_KEY, True)
        self.accept()


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
    "Don't show again" beats a pending version bump, and leaving the last-seen
    record where it stood is what lets the Help-menu toggle hand the ordinary
    once-per-version rules back intact, pending bump included.
    """
    if settings is None:
        settings = QSettings(ORG, APP)
    if current is None:
        current = current_version_str()
    if whats_new_suppressed(settings.value(WHATSNEW_SUPPRESS_KEY, WHATSNEW_SUPPRESS_DEFAULT)):
        return False
    stored = settings.value(key)
    if not whats_new_due(stored, current):
        return False
    if show is None:
        # the default dialog gets this same store, so its "Don't show again"
        # button writes where this gate reads; an injected show is a test seam
        # with the historical (parent, version, last_seen) signature
        show = partial(_default_show, settings=settings)
    show(parent, current, stored)
    settings.setValue(key, current)
    return True


def show_whats_new(parent, current=None, show=None):
    """Show the What's-new dialog on demand (Help -> What's new).

    Unlike ``maybe_show_whats_new`` there is no once-per-version gate, no
    "Don't show again" suppression (a menu click is an explicit request, not a
    popup), and the stored last-seen version is neither consulted nor updated:
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

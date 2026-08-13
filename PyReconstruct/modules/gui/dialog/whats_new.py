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
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt, QSettings, QEvent

from PyReconstruct.modules.backend.updater.install_info import current_version_str
from PyReconstruct.modules.gui.main.first_launch import (
    whats_new_due, whats_new_content, github_release_url, WHATSNEW_KEY,
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
        self.setText(markup)

    def changeEvent(self, event):
        # getattr: change events can arrive from inside QLabel.__init__, before
        # _markup is assigned.
        if event.type() == QEvent.Type.PaletteChange and getattr(self, "_markup", None):
            super().setText("")
            super().setText(self._markup)
        super().changeEvent(event)


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

    def __init__(self, parent, version, last_seen=None, content=None, url=None):
        super().__init__(parent)
        self._version = version
        if content is None:
            content = whats_new_content(version, last_seen)
        if url is None:
            url = github_release_url(version)

        self.setWindowTitle(
            f"What's new in PyReconstruct {version}" if version
            else "What's new in PyReconstruct"
        )
        self.setMinimumWidth(540)
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

        if content.get("date"):
            released = QLabel(f"Released {content['date']}")
            released.setEnabled(False)  # muted, secondary to the version
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
        self._notes = make_notes_browser(content["body"], min_height=260)
        lay.addWidget(self._notes)

        # The provenance line itself: italic, at the ordinary text colour, and a
        # jump link to the project home page. The italic is the aside register
        # the markdown `_..._` gave it inside the notes, and it is kept. What is
        # deliberately *not* kept is the muting: this label first landed dimmed
        # by `setEnabled(False)`, the way the release date above it is, and the
        # disabled palette paints it at about 1.6:1 against the dialog
        # background (measured on the rendered widget, offscreen/Fusion:
        # #bebebe on #efefef). At that contrast it reads as switched-off rather
        # than as a quiet aside, and this is the one line a lab needs in order
        # to report an issue to the right person. So it is an ordinary *enabled*
        # label in the normal text colour -- italic for the register, full
        # contrast for the legibility.
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
            self._byline = LinkLabel(
                f'{before}<a href="{HOMEPAGE_URL}">{name}</a>{after}' if name
                else before
            )
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
        # AlignTop: when the byline wraps onto a second line at a narrow width,
        # the link stays level with the byline's first line rather than
        # floating mid-row.
        link = LinkLabel(f'<a href="{url}">Full release notes on GitHub ↗</a>')
        link.setOpenExternalLinks(True)
        footer.addWidget(link, 0, Qt.AlignTop)
        lay.addLayout(footer)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Got it")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)


def _default_show(parent, version, last_seen=None, content=None):
    """Construct and show the dialog modelessly, transiently."""
    dialog = WhatsNewDialog(parent, version, last_seen=last_seen, content=content)
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

    The pure gate lives in ``whats_new_due``; this wires it to QSettings and the
    dialog. The stored last-seen version is threaded into the builder so the
    dialog can summarise everything missed since then. ``settings`` / ``current``
    / ``show`` are injectable for headless testing. Returns True if shown.
    """
    if settings is None:
        settings = QSettings(ORG, APP)
    if current is None:
        current = current_version_str()
    stored = settings.value(key)
    if not whats_new_due(stored, current):
        return False
    (show or _default_show)(parent, current, stored)
    settings.setValue(key, current)
    return True


def show_whats_new(parent, current=None, show=None):
    """Show the What's-new dialog on demand (Help -> What's new).

    Unlike ``maybe_show_whats_new`` there is no once-per-version gate and the
    stored last-seen version is neither consulted nor updated: the dialog always
    opens on the running version's notes rather than a fresh-install welcome.
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

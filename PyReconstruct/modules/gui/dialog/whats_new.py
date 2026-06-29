"""First-launch "What's new" dialog.

Shows the running version's release notes once per version -- on a fresh install
or after an update. It reuses the updater dialog's markdown notes renderer. It is
a normal, dismissible, *modeless* dialog: it never blocks startup or steals focus
the way a prompt would.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, QSettings

from PyReconstruct.modules.gui.dialog.update_dialog import make_notes_browser
from PyReconstruct.modules.backend.updater.install_info import current_version_str
from PyReconstruct.modules.gui.main.first_launch import (
    whats_new_due, release_notes_markdown, github_release_url, WHATSNEW_KEY,
)

ORG, APP = "KHLab", "PyReconstruct"


class WhatsNewDialog(QDialog):
    """A dismissible, modeless summary of what changed in this version."""

    def __init__(self, parent, version, notes_markdown=None, url=None):
        super().__init__(parent)
        self._version = version
        if notes_markdown is None:
            notes_markdown = release_notes_markdown(version)
        if url is None:
            url = github_release_url(version)

        self.setWindowTitle(f"What's new in PyReconstruct {version}")
        self.setMinimumWidth(540)
        self.setModal(False)  # modeless: does not block the app

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>What's new in {version}</b>"))

        self._notes = make_notes_browser(notes_markdown, min_height=260)
        lay.addWidget(self._notes)

        link = QLabel(f'<a href="{url}">Full release notes on GitHub ↗</a>')
        link.setTextFormat(Qt.RichText)
        link.setOpenExternalLinks(True)
        lay.addWidget(link)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Got it")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)


def _default_show(parent, version):
    """Construct and show the dialog modelessly, transiently."""
    dialog = WhatsNewDialog(parent, version)
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
    dialog. ``settings`` / ``current`` / ``show`` are injectable for headless
    testing. Returns True if the dialog was shown.
    """
    if settings is None:
        settings = QSettings(ORG, APP)
    if current is None:
        current = current_version_str()
    stored = settings.value(key)
    if not whats_new_due(stored, current):
        return False
    (show or _default_show)(parent, current)
    settings.setValue(key, current)
    return True

"""GUI-free user notifications for the core data model (M11 seam).

`Series` surfaces user-facing messages (e.g. a failed-save warning) through a
`Notifier` rather than importing the GUI `notify` helper directly, so the data
model no longer depends on Qt/GUI to notify. GUI callers get the `QtNotifier`
default, whose behavior is identical to the previous inline guard: a
notification is shown only when a Qt application is running and the platform is
not the offscreen (headless) plugin; otherwise it stays silent. Headless
callers and tests can inject `NullNotifier` (pure Python, no Qt, never
notifies).

`notify` returns True if it actually surfaced a notification and False
otherwise, so a caller can fall back to its own reporting -- matching the prior
code, which printed the message (without the GUI `notify` helper's blocking
"Press Enter" prompt) whenever no GUI notification was shown.
"""

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Minimal user-notification interface, GUI-free at the core."""

    @abstractmethod
    def notify(self, message) -> bool:
        """Surface ``message`` to the user.

        Return True if a notification was actually shown, False otherwise so a
        caller can fall back to its own (e.g. headless) reporting.
        """

    def notify_error(self, message, report) -> bool:
        """Surface an error ``message`` alongside a copyable ``report``.

        The default degrades to a plain ``notify(message)`` (dropping the
        report), so non-GUI notifiers need no change. GUI notifiers override
        this to show the report in a copyable dialog. Returns True if a
        notification was actually shown.
        """
        return self.notify(message)

    def confirm(self, message, title="Confirm"):
        """Ask the user to approve ``message`` before something destructive.

        Returns True if they approved, False if they declined, and None if
        there was nobody to ask. None is not consent: it means the caller is
        running without a user (a script, a test, the offscreen platform) and
        should carry on doing what it did before this question existed, since
        refusing every such run would break loading a series in a script.

        The default never asks, so non-GUI notifiers need no change and can
        never block. Only the Qt adapter overrides it.
        """
        return None


class QtNotifier(Notifier):
    """Default notifier backed by the GUI ``notify`` helper (prior behavior).

    This is the Qt adapter layer, so it imports ``notify`` / ``QApplication`` /
    ``qt_offscreen`` -- lazily, so that importing this module and using
    ``NullNotifier`` require no Qt/GUI. The guard is identical to the previous
    inline guard: show a notification only when a Qt application is running and
    the platform is not offscreen; otherwise stay silent and return False so the
    caller can report the message itself. Guarding here (rather than inside the
    GUI ``notify`` helper) avoids that helper's blocking "Press Enter" prompt in
    headless runs, exactly as before.
    """

    def notify(self, message):
        from PySide6.QtWidgets import QApplication
        from PyReconstruct.modules.gui.utils import notify
        from PyReconstruct.modules.gui.utils.utils import qt_offscreen
        if QApplication.instance() is not None and not qt_offscreen:
            notify(message)
            return True
        return False

    def notify_error(self, message, report):
        from PySide6.QtWidgets import QApplication
        from PyReconstruct.modules.gui.utils.utils import qt_offscreen
        if QApplication.instance() is not None and not qt_offscreen:
            from PyReconstruct.modules.gui.utils.errors import show_save_error
            show_save_error(message, report)
            return True
        return False

    def confirm(self, message, title="Confirm"):
        """Ask through the GUI ``notifyConfirm`` helper, or not at all.

        The same guard as ``notify``, and for the same reason: ``notifyConfirm``
        falls back to reading a yes/no from stdin when no GUI is up, which would
        block a script or a test forever. Guarding here means that branch is
        never reached, and the caller gets None ("nobody to ask") instead.
        """
        from PySide6.QtWidgets import QApplication
        from PyReconstruct.modules.gui.utils.utils import qt_offscreen
        if QApplication.instance() is not None and not qt_offscreen:
            from PyReconstruct.modules.gui.utils import notifyConfirm
            return bool(notifyConfirm(message, title=title))
        return None


class NullNotifier(Notifier):
    """No-op notifier for headless use and tests (pure Python, no Qt).

    Never surfaces a notification and always returns False, so callers fall back
    to their own reporting.
    """

    def notify(self, message):
        return False

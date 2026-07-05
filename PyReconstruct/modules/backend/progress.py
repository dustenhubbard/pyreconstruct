"""GUI-free progress reporting for the core data model (M11 seam).

Long-running `Series` operations report progress and honor cancellation through
a `ProgressReporter` rather than creating a Qt progress bar directly, so the
data model no longer depends on Qt/GUI for progress. GUI callers get the
`QtProgressReporter` default, whose behavior is identical to the previous direct
`getProgbar` usage (same text, same cancelability, same 0-100 `setValue`
scaling, and cancellation via `wasCanceled`). Headless callers and tests can
inject `NullProgressReporter` (pure Python, no Qt, never cancels).

One reporter corresponds to one operation, mirroring a single `getProgbar`
handle. Drive it as: construct with the label and whether it is cancelable, call
``set_progress(percent)`` with a 0-100 value as work advances, check
``was_canceled()`` to abort, and ``finish()`` (or exit the ``with`` block) to
finalize to 100%.
"""

from abc import ABC, abstractmethod


class ProgressReporter(ABC):
    """Progress + cancellation for a single operation, GUI-free at the core.

    ``text`` is the label shown to the user and ``cancel`` whether the operation
    can be canceled; both mirror the corresponding ``getProgbar`` arguments.
    """

    def __init__(self, text: str = "", cancel: bool = True):
        self.text = text
        self.cancel = cancel

    @abstractmethod
    def set_progress(self, percent) -> None:
        """Set progress on a 0-100 scale (mirrors ``QProgressDialog.setValue``)."""

    @abstractmethod
    def was_canceled(self) -> bool:
        """Return True if the user has requested cancellation."""

    def finish(self) -> None:
        """Finalize the reporter to 100%."""
        self.set_progress(100)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # finalize on a clean exit only; on an exception the operation did not
        # complete, so leave the reporter where it was (matching the prior code,
        # which never forced 100% on a canceled/failed path)
        if exc_type is None:
            self.finish()
        return False


class QtProgressReporter(ProgressReporter):
    """Default reporter backed by ``getProgbar`` (identical to prior behavior).

    This is the Qt adapter layer, so it imports ``getProgbar`` -- lazily, so
    that importing this module and using ``NullProgressReporter`` require no Qt.
    A fresh progress bar is created per reporter, exactly as ``getProgbar`` was
    called fresh per operation before. ``set_progress`` forwards to ``setValue``
    (same scaling) and ``was_canceled`` reads ``wasCanceled``, so cancellation
    is preserved.
    """

    def __init__(self, text: str = "", cancel: bool = True):
        super().__init__(text, cancel)
        from PyReconstruct.modules.gui.utils import getProgbar
        self._progbar = getProgbar(text=text, cancel=cancel)

    def set_progress(self, percent):
        self._progbar.setValue(percent)

    def was_canceled(self):
        return self._progbar.wasCanceled()


class NullProgressReporter(ProgressReporter):
    """No-op reporter for headless use and tests (pure Python, no Qt).

    Progress updates are dropped and cancellation is never requested, matching
    the text-mode ``BasicProgbar.wasCanceled`` (always False).
    """

    def set_progress(self, percent):
        pass

    def was_canceled(self):
        return False

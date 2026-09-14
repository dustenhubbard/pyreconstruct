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

import time
from abc import ABC, abstractmethod

# No estimate before this much of the work is done and this much time has
# passed: the first few percent of a job say little about the rest, and a
# job that finishes in a couple of seconds never needs an estimate at all.
ETA_MIN_PERCENT = 5
ETA_MIN_ELAPSED = 2.0


def estimate_remaining(elapsed: float, percent: float):
    """Seconds left, assuming the rate so far holds; None if too early to say.

        Params:
            elapsed (float): seconds since the first progress report
            percent (float): work done so far, 0-100
        Returns:
            (float | None): the estimate, or None below the thresholds
    """
    if percent < ETA_MIN_PERCENT or elapsed < ETA_MIN_ELAPSED or percent >= 100:
        return None
    return elapsed * (100 - percent) / percent


def format_remaining(seconds: float) -> str:
    """A rounded, human phrase for a time estimate: "about 40 seconds left"."""
    if seconds < 60:
        n = max(5, int(round(seconds / 5.0)) * 5)
        return f"about {n} seconds left"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"about {minutes} minute{'s' if minutes != 1 else ''} left"
    hours, minutes = divmod(minutes, 60)
    if minutes == 0:
        return f"about {hours} hour{'s' if hours != 1 else ''} left"
    return f"about {hours} h {minutes} min left"


class ProgressReporter(ABC):
    """Progress + cancellation for a single operation, GUI-free at the core.

    ``text`` is the label shown to the user and ``cancel`` whether the operation
    can be canceled; both mirror the corresponding ``getProgbar`` arguments.

    The reporter can also keep a time estimate, when asked (``eta=True``).
    ``set_progress`` records when the first report arrived; ``eta_text()``
    then reads "about 40 seconds left" once enough of the job has run to say
    (see ``estimate_remaining``), and is None before that. Only the operations
    that ask for it show one: his call (2026-09-14) was the recolor of many
    objects, not every progress dialog in the app, and an opening series must
    not carry one.
    """

    def __init__(self, text: str = "", cancel: bool = True, eta: bool = False):
        self.text = text
        self.cancel = cancel
        self.eta = eta
        self._started = None
        self._clock = time.monotonic

    def note_progress(self, percent) -> None:
        """Record a report for the estimate. Subclasses call this first."""
        if self._started is None:
            self._started = self._clock()
        self._percent = percent

    def eta_text(self):
        """The estimate phrase for the last report, or None if too early."""
        if self._started is None:
            return None
        seconds = estimate_remaining(self._clock() - self._started, self._percent)
        return None if seconds is None else format_remaining(seconds)

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

    def __init__(self, text: str = "", cancel: bool = True, eta: bool = False):
        super().__init__(text, cancel, eta)
        from PyReconstruct.modules.gui.utils import getProgbar
        self._progbar = getProgbar(text=text, cancel=cancel)

    def set_progress(self, percent):
        if self.eta:
            self.note_progress(percent)
            eta = self.eta_text()
            # the text-mode BasicProgbar has no label to update
            if eta and hasattr(self._progbar, "setLabelText"):
                self._progbar.setLabelText(f"{self.text}\n{eta}")
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

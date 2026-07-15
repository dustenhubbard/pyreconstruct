"""Copyable error/diagnostic reports and the handled save-error path.

The frozen app has no console, so a failure must surface a report (shown +
copyable) carrying the full traceback + environment, the builders must never
themselves raise (they run inside error handlers), and a *handled* save failure
must reach the copyable dialog through the Qt-free Notifier seam -- not only
uncaught exceptions.
"""
import sys

from PyReconstruct.modules.backend.func.error_report import (
    build_error_report,
    build_diagnostic_report,
    build_error_report_from_exception,
)
from PyReconstruct.modules.backend.notifier import Notifier, NullNotifier
from PyReconstruct.modules.datatypes.series import Series


def test_report_has_traceback_and_context():
    try:
        raise ValueError("boom-marker-123")
    except ValueError:
        exctype, value, tb = sys.exc_info()
    report = build_error_report(exctype, value, tb)
    assert "boom-marker-123" in report     # the exception message
    assert "ValueError" in report          # the exception type
    assert "Traceback" in report           # the stack
    assert "Platform:" in report and "Python:" in report   # context


def test_report_never_raises_on_bad_input():
    # the exception hook must not fail even on degenerate inputs
    assert isinstance(build_error_report(None, None, None), str)
    assert isinstance(build_error_report(ValueError, ValueError("x"), None), str)


def test_diagnostic_report_has_context_but_no_traceback():
    report = build_diagnostic_report()
    assert "Platform:" in report and "Python:" in report
    assert "Traceback" not in report       # no exception -> no stack


def test_report_from_exception_uses_its_own_traceback():
    try:
        raise OSError("[WinError 5] Access is denied")
    except OSError as e:
        report = build_error_report_from_exception(e)
    assert "WinError 5" in report and "Traceback" in report


def test_notifier_notify_error_defaults_to_notify():
    # NullNotifier has no notify_error override; the base default degrades to
    # notify() (which returns False), so non-GUI notifiers need no change.
    assert NullNotifier().notify_error("msg", "report") is False


class _CapturingNotifier(Notifier):
    """Records notify_error calls; pure Python, no Qt."""

    def __init__(self):
        self.calls = []

    def notify(self, message):
        return False

    def notify_error(self, message, report):
        self.calls.append((message, report))
        return True


class _StubSeries:
    """Minimal stand-in exposing just what _surfaceSaveError touches."""

    def __init__(self, notifier):
        self._n = notifier

    def _notifier(self):
        return self._n


def test_surface_save_error_routes_copyable_report_through_notifier():
    cap = _CapturingNotifier()
    try:
        raise OSError("[WinError 5] Access is denied")
    except OSError as err:
        Series._surfaceSaveError(_StubSeries(cap), "/path/to/proj.jser", err)

    assert cap.calls, "handled save error must reach notify_error"
    message, report = cap.calls[0]
    # the human message keeps the reassurance that data is safe
    assert "Save failed" in message and "/path/to/proj.jser" in message
    # the copyable report carries the traceback + the specific error
    assert "WinError 5" in report and "Traceback" in report

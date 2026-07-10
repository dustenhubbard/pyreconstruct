"""The crash-report builder behind the copyable error dialog.

The frozen app has no console, so the report (shown + copied to clipboard) must
carry the full traceback + context, and the builder must never itself raise
(it runs inside the global exception hook).
"""
import sys

from PyReconstruct.modules.gui.utils.errors import build_error_report


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

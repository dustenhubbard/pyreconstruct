"""Paste-ready diagnostic / crash reports (Qt-free).

Kept free of Qt so both the GUI error hook and the Qt-free data model
(``Series``, the M11 seam) can build a report; the GUI layer renders it in a
copyable dialog. Every function here must never raise -- a report builder that
throws while handling an error would mask the original problem.
"""
import platform
import traceback as _traceback


def _context_lines() -> list:
    """Version / OS / Python lines, each guarded so a lookup failure is skipped."""
    lines = []
    try:
        from PyReconstruct.modules.backend.updater.install_info import (
            current_version_str,
        )
        lines.append(f"Version:  {current_version_str()}")
    except Exception:
        pass
    try:
        lines.append(f"Platform: {platform.platform()}")
        lines.append(f"Python:   {platform.python_version()}")
    except Exception:
        pass
    return lines


def build_diagnostic_report() -> str:
    """A report with just the environment context (no traceback).

    For the on-demand "Copy diagnostic report" action, where there is no
    exception -- only the version/OS/Python the user is running.
    """
    lines = ["PyReconstruct diagnostic report"]
    lines += _context_lines() or ["(context unavailable)"]
    return "\n".join(lines)


def build_error_report(exctype, value, tb) -> str:
    """A paste-ready crash report: environment context plus the full traceback.

    Never raises -- it runs inside the global exception hook and the handled
    save-error path, neither of which may fail.
    """
    lines = ["PyReconstruct error report"]
    lines += _context_lines()
    lines.append("")
    try:
        tb_text = "".join(_traceback.format_exception(exctype, value, tb)).rstrip()
    except Exception:
        tb_text = f"{getattr(exctype, '__name__', exctype)}: {value}"
    lines.append(tb_text or "(no traceback available)")
    return "\n".join(lines)


def build_error_report_from_exception(err: BaseException) -> str:
    """``build_error_report`` for a caught exception object.

    Convenience for handled paths that hold the exception (not ``sys.exc_info``);
    uses the exception's own ``__traceback__``.
    """
    return build_error_report(type(err), err, getattr(err, "__traceback__", None))

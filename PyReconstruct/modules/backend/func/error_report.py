"""Paste-ready diagnostic / crash reports (Qt-free).

Kept free of Qt so both the GUI error hook and the Qt-free data model
(``Series``, the M11 seam) can build a report; the GUI layer renders it in a
copyable dialog. Every function here must never raise -- a report builder that
throws while handling an error would mask the original problem.
"""
import platform
import traceback as _traceback
from urllib.parse import quote as _quote


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


# The issue forms' prefillable field (.github/ISSUE_TEMPLATE/bug.yml and
# feature.yml both declare a textarea with this id). GitHub fills a form
# field from a query parameter of the same name.
ISSUE_FORM_SETUP_FIELD = "setup"


def prefilled_issue_url(form_url: str) -> str:
    """``form_url`` with the setup field prefilled from the diagnostic lines.

    ``form_url`` already names its form (``...?template=bug.yml``), so the
    field rides along as ``&setup=``. Never raises: with nothing to add, or on
    any failure, the plain form URL comes back and the filer fills the field by
    hand.
    """
    try:
        lines = _context_lines()
        if not lines:
            return form_url
        joiner = "&" if "?" in form_url else "?"
        return f"{form_url}{joiner}{ISSUE_FORM_SETUP_FIELD}={_quote(chr(10).join(lines), safe='')}"
    except Exception:
        return form_url


# The bug form's error textarea (.github/ISSUE_TEMPLATE/bug.yml, id "error").
ISSUE_FORM_ERROR_FIELD = "error"
# Ceiling for the whole prefilled link. GitHub answers a request line past
# about 8 KB with 414 and browsers cap URLs of their own, while a traceback
# through Qt can run to tens of KB, so the report is trimmed to fit under this.
ISSUE_URL_MAX_CHARS = 7000
# Marks the cut when a report is trimmed. The full text is still on the
# clipboard button and in the log file.
REPORT_TRIM_MARKER = "\n[...]\n"


def issue_url_for_report(form_url: str, report: str) -> str:
    """The bug form with the setup field prefilled and ``report`` in the error field.

    Keeps the link under ``ISSUE_URL_MAX_CHARS`` by cutting the middle of the
    report: the head keeps the version lines and where the traceback starts, the
    tail keeps the raise site and the message, which is the part that names the
    bug. Never raises: on any failure the setup-only link comes back, and failing
    that the plain form.
    """
    try:
        base = prefilled_issue_url(form_url)
        if not report:
            return base
        joiner = "&" if "?" in base else "?"
        prefix = f"{base}{joiner}{ISSUE_FORM_ERROR_FIELD}="
        budget = ISSUE_URL_MAX_CHARS - len(prefix)
        encoded = _quote(report, safe="")
        keep = len(report)
        while len(encoded) > budget:
            # Shrink by a quarter each pass and re-measure: percent-encoding
            # inflates unevenly, so the fit is checked on the encoded text.
            keep = int(keep * 0.75)
            if keep < 200:
                return base
            head = report[: keep // 3]
            tail = report[-(keep - keep // 3):]
            encoded = _quote(head + REPORT_TRIM_MARKER + tail, safe="")
        return prefix + encoded
    except Exception:
        try:
            return prefilled_issue_url(form_url)
        except Exception:
            return form_url

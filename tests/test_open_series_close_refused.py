"""Opening a series when a held working file refuses the close of the last one.

Closing a series moves its working files aside before deleting anything. When
that move fails (on Windows, a working file held open by another program or a
sync client can refuse it), the open stops there. What is pinned here:

  * the app's error window opens: the failed close is not quiet
  * the window keeps the series it had, with every working file in place,
    and a pass over it reads every section
"""
import os
import sys

import pytest

pytestmark = pytest.mark.gui


def test_an_open_a_held_file_stops_keeps_the_series_and_says_so(
    main_window, monkeypatch, tmp_path
):
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.gui.utils import errors
    window = main_window
    first = window.series
    hidden_dir = first.hidden_dir
    before = sorted(os.listdir(hidden_dir))

    rename = os.rename

    def held(src, dst, *args, **kwargs):
        if os.path.normpath(src) == hidden_dir:
            raise PermissionError(13, "Permission denied", src)
        return rename(src, dst, *args, **kwargs)

    shown = []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    monkeypatch.setattr(
        logging_setup, "log_file_path", lambda: str(tmp_path / "log.txt")
    )
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)
    # set in the test body: pytest-qt puts its own hook in for the call
    monkeypatch.setattr(sys, "excepthook", errors.customExcepthook)
    monkeypatch.setattr(os, "rename", held)
    try:
        # File > Open closes the series before it asks for the next one
        window.open_act.trigger()
    finally:
        monkeypatch.setattr(os, "rename", rename)

    assert len(shown) == 1 and "PermissionError" in shown[0]
    assert window.series is first and not first.closed
    assert sorted(os.listdir(hidden_dir)) == before
    visited = [
        snum for snum, _section
        in first.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(first.sections)

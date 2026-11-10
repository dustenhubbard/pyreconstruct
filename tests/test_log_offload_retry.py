"""A failed history offload can be retried without changing retained rows."""
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from PyReconstruct.modules.datatypes import log as log_module
from PyReconstruct.modules.datatypes.log import LOG_HEADER, LogSet


HEADER = LOG_HEADER + "\n"
RECENT1 = "26-11-01, 12:00, alice, axon1, 1, Modify trace(s)\n"
OLD = "20-01-01, 12:00, alice, axon2, 2, Create trace(s)\n"
RECENT2 = "26-11-02, 12:00, alice, axon3, 3, Modify trace(s)\n"
ORIGINAL = HEADER + RECENT1 + OLD + RECENT2


@pytest.fixture
def history_files(tmp_path, monkeypatch):
    monkeypatch.setattr(log_module, "remove_days_from_today", lambda days: date(2026, 10, 1))
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    existing = hidden / "existing_log.csv"
    existing.write_text(ORIGINAL, encoding="utf-8")
    return hidden, existing, tmp_path / "offloaded.csv"


@pytest.mark.parametrize("failure_mode", ["export_write", "export_close", "export_open", "replace"])
def test_retry_after_failure_keeps_each_retained_row_once(history_files, monkeypatch, failure_mode):
    hidden, existing, output = history_files
    real_open = Path.open
    real_replace = Path.replace

    @contextmanager
    def failing_open(path, *args, **kwargs):
        if path == output and failure_mode == "export_open":
            raise OSError("injected offload failure")
        with real_open(path, *args, **kwargs) as stream:
            class FailingWriter:
                def write(self, text):
                    if text == OLD:
                        raise OSError("injected offload failure")
                    return stream.write(text)

            yield FailingWriter() if path == output and failure_mode == "export_write" else stream
        if path == output and failure_mode == "export_close":
            raise OSError("injected offload failure")

    def failing_replace(path, target):
        if target == existing:
            raise OSError("injected offload failure")
        return real_replace(path, target)

    with monkeypatch.context() as failure:
        failure.setattr(Path, "open", failing_open)
        if failure_mode == "replace":
            failure.setattr(Path, "replace", failing_replace)
        with pytest.raises(OSError, match="injected offload failure"):
            LogSet.exportLogHistory(str(hidden), str(output), 30)

    files_after_failure = set(hidden.iterdir())
    assert existing.read_bytes() == ORIGINAL.encode("utf-8")
    LogSet.exportLogHistory(str(hidden), str(output), 30)
    assert existing.read_text(encoding="utf-8") == HEADER + RECENT1 + RECENT2
    assert output.read_text(encoding="utf-8") == HEADER + OLD
    assert files_after_failure == {existing}
    assert set(hidden.iterdir()) == {existing}


def test_offload_ignores_a_temporary_file_from_an_earlier_attempt(history_files):
    hidden, existing, output = history_files
    stale = hidden / "new_log.csv"
    stale.write_text(HEADER + RECENT1, encoding="utf-8")

    LogSet.exportLogHistory(str(hidden), str(output), 30)

    assert existing.read_text(encoding="utf-8") == HEADER + RECENT1 + RECENT2
    assert output.read_text(encoding="utf-8") == HEADER + OLD
    assert stale.read_text(encoding="utf-8") == HEADER + RECENT1
    assert set(hidden.iterdir()) == {existing, stale}

"""Regression test for importFromSeries crashing when the open is cancelled.

Series.openJser returns None when the user cancels the "Opening series..."
progress bar. importFromSeries passed that straight into checkMag(self.series,
o_series), which dereferences o_series.avg_mag -> AttributeError on None. The
sibling openSeries already guards this exact case; importFromSeries did not.
Exercised against a duck-typed stub with the module-level collaborators
monkeypatched, so no real MainWindow / Qt is required.
"""
import types

from PyReconstruct.modules.gui.main import main_window as mw


def test_import_from_series_aborts_when_open_cancelled(monkeypatch):
    monkeypatch.setattr(
        mw, "FileDialog",
        types.SimpleNamespace(get=lambda *a, **k: "/some/series.jser"),
    )
    # simulate the user cancelling the progress bar -> openJser returns None
    monkeypatch.setattr(mw.Series, "openJser", staticmethod(lambda *a, **k: None))

    constructed = {"hit": False}

    def fake_dialog(*a, **k):
        constructed["hit"] = True
        return types.SimpleNamespace(exec=lambda: (None, False))

    monkeypatch.setattr(mw, "ImportSeriesDialog", fake_dialog)

    stub = types.SimpleNamespace(
        series=types.SimpleNamespace(avg_mag=0.01),
        saveAllData=lambda: None,
    )

    mw.MainWindow.importFromSeries(stub)  # must not raise AttributeError

    assert constructed["hit"] is False, (
        "must abort on a cancelled open, not proceed to the import dialog"
    )


def test_import_from_series_proceeds_for_a_valid_series(monkeypatch):
    """A real (non-None) opened series still reaches the import dialog -- the
    guard must not abort valid input."""
    monkeypatch.setattr(
        mw, "FileDialog",
        types.SimpleNamespace(get=lambda *a, **k: "/some/series.jser"),
    )
    o_series = types.SimpleNamespace(avg_mag=0.01, close=lambda: None)
    monkeypatch.setattr(mw.Series, "openJser", staticmethod(lambda *a, **k: o_series))
    monkeypatch.setattr(mw, "checkMag", lambda s, o: True)

    constructed = {"hit": False}

    def fake_dialog(*a, **k):
        constructed["hit"] = True
        # confirmed=False so the method returns right after the dialog
        return types.SimpleNamespace(exec=lambda: (None, False))

    monkeypatch.setattr(mw, "ImportSeriesDialog", fake_dialog)

    stub = types.SimpleNamespace(
        series=types.SimpleNamespace(avg_mag=0.01),
        saveAllData=lambda: None,
    )

    mw.MainWindow.importFromSeries(stub)

    assert constructed["hit"] is True

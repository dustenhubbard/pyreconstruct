"""Regression tests for missing-return-after-guard bugs in main_window.

Same bug class as the setSeriesMag fix: a validation guard notifies the user
but (before the fix) lacked a `return`, so execution fell through to a
state-mutating action using the rejected input. The GUI methods are exercised
against duck-typed stubs with the module-level collaborators monkeypatched, so
no real MainWindow / Qt event loop is required.

Covered:
  * newFromNgZarr        — non-zarr directory selection
  * importFromZarrLabels — non-zarr directory selection
  * calibrateMag         — no traces selected
"""
import types
import pytest

from PyReconstruct.modules.gui.main import main_window as mw


# --------------------------------------------------------------------------
# newFromNgZarr / importFromZarrLabels: a directory not ending in "zarr" must
# abort before reaching the QuickDialog (and the downstream build/import).
# tmp_path is a real, empty directory whose name does not end in "zarr", so the
# intervening os.listdir() runs harmlessly either way; the QuickDialog is the
# marker proving whether the function aborted.
# --------------------------------------------------------------------------
def _patch_zarr_dialogs(monkeypatch, selected_dir):
    notified = []
    quick_called = {"hit": False}

    def fake_quick_get(*args, **kwargs):
        quick_called["hit"] = True
        return (None, False)

    monkeypatch.setattr(
        mw, "FileDialog",
        types.SimpleNamespace(get=lambda *a, **k: str(selected_dir)),
    )
    monkeypatch.setattr(
        mw, "QuickDialog", types.SimpleNamespace(get=fake_quick_get)
    )
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))
    return notified, quick_called


@pytest.mark.parametrize("method", ["newFromNgZarr", "importFromZarrLabels"])
def test_invalid_zarr_selection_aborts(monkeypatch, tmp_path, method):
    notified, quick_called = _patch_zarr_dialogs(monkeypatch, tmp_path)
    stub = types.SimpleNamespace()

    getattr(mw.MainWindow, method)(stub)

    assert notified, f"{method} should warn on a non-zarr selection"
    assert quick_called["hit"] is False, (
        f"{method} must abort after the warning, not proceed to the dialog"
    )


# --------------------------------------------------------------------------
# calibrateMag: with no traces selected, names == [] -> the function must warn
# and abort, NOT fall through to field.calibrateMag({}) (which divides by zero).
# --------------------------------------------------------------------------
def test_calibrate_mag_with_no_traces_aborts(monkeypatch):
    notified = []
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))

    field_calls = []

    class _Field:
        section = types.SimpleNamespace(selected_traces=[])

        def calibrateMag(self, trace_lengths):
            field_calls.append(trace_lengths)

    stub = types.SimpleNamespace(saveAllData=lambda: None, field=_Field())

    mw.MainWindow.calibrateMag(stub)

    assert notified, "should warn when no traces are selected"
    assert field_calls == [], "must not attempt calibration with no traces"


def test_calibrate_mag_with_explicit_lengths_still_calibrates(monkeypatch):
    """An explicit trace_lengths dict bypasses the gather branch and calibrates."""
    field_calls = []

    class _Field:
        section = types.SimpleNamespace(selected_traces=[])

        def calibrateMag(self, trace_lengths):
            field_calls.append(trace_lengths)

    stub = types.SimpleNamespace(saveAllData=lambda: None, field=_Field())

    mw.MainWindow.calibrateMag(stub, trace_lengths={"a": 1.0})

    assert field_calls == [{"a": 1.0}]

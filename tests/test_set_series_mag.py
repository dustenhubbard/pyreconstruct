"""Regression test for setSeriesMag's missing early return.

setSeriesMag rejects a non-positive magnification with a notification, but
(before the fix) fell through and still called saveAllData() + field.setMag()
with the invalid value. The dialog method is exercised against a duck-typed
stub so no real MainWindow / Qt event loop is required.
"""
import types
import pytest

from PyReconstruct.modules.gui.main import main_window as mw


class _FieldStub:
    def __init__(self):
        self.mag = None

    def setMag(self, m):
        self.mag = m


class _MainWindowStub:
    def __init__(self, avg_mag=0.01):
        self.series = types.SimpleNamespace(avg_mag=avg_mag)
        self.field = _FieldStub()
        self.saved = False

    def saveAllData(self):
        self.saved = True


def _patch_dialog(monkeypatch, value, confirmed):
    class _FakeDialog:
        @staticmethod
        def getDouble(*args, **kwargs):
            return (value, confirmed)
    monkeypatch.setattr(mw, "QInputDialog", _FakeDialog)
    notified = []
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))
    return notified


@pytest.mark.parametrize("value", [-1.0, 0.0])
def test_non_positive_mag_is_rejected_and_not_applied(monkeypatch, value):
    """A non-positive, confirmed value must notify and NOT mutate state."""
    notified = _patch_dialog(monkeypatch, value, confirmed=True)
    stub = _MainWindowStub()

    mw.MainWindow.setSeriesMag(stub)

    assert notified, "user should be notified that mag must be > 0"
    assert stub.field.mag is None, "invalid magnification must not be applied"
    assert stub.saved is False, "data must not be saved for an invalid magnification"


def test_valid_mag_is_applied(monkeypatch):
    """A valid, confirmed value still saves and applies the magnification."""
    _patch_dialog(monkeypatch, 0.005, confirmed=True)
    stub = _MainWindowStub()

    mw.MainWindow.setSeriesMag(stub)

    assert stub.saved is True
    assert stub.field.mag == 0.005


def test_cancel_does_nothing(monkeypatch):
    """Cancelling the dialog leaves state untouched."""
    _patch_dialog(monkeypatch, 0.005, confirmed=False)
    stub = _MainWindowStub()

    mw.MainWindow.setSeriesMag(stub)

    assert stub.saved is False
    assert stub.field.mag is None

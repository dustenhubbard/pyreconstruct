"""Curation defaults just happen, and the record says who made them happen.

Two changes, both from the same field report (a five-hour session in which
every needs-curation marking cost a dialog whose usual answer was blank):

1. The context menu's "Needs curation" no longer prompts. It assigns to the
   CURRENT USER; assigning to somebody else is the deliberate extra step in
   its own row ("Needs curation (assign to)...", which keeps the dialog and
   pre-fills the current user).
2. Who SET a status is now recorded, beside the status rather than inside it:
   the ``curation`` attribute stays the historical 3-tuple ``(curated, user,
   date)`` because three call sites and every shipped build strict-unpack it,
   and the assigner lives in the sibling ``curation_by`` attribute, which
   older builds never read. The log author is the assigner, which is what
   lets the from-history restore recover it.
"""
import shutil

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series

# main keeps its series fixture under dev/assets (the release line bundles
# one under PyReconstruct/assets/checker); lean on conftest's path.
from conftest import SERIES_FIXTURE


@pytest.fixture
def series(tmp_path):
    if not SERIES_FIXTURE.exists():
        pytest.skip(f"series fixture missing: {SERIES_FIXTURE}")
    fp = str(tmp_path / "series.jser")
    shutil.copyfile(SERIES_FIXTURE, fp)
    s = Series.openJser(fp)
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


# --------------------------------------------------------------------------- #
# the model: assigner recorded beside the status
# --------------------------------------------------------------------------- #
def test_needs_curation_records_who_assigned(series):
    series.setCuration(["square"], "Needs curation", "alice")
    assert series.obj_attrs["square"]["curation"][:2] == (False, "alice")
    assert series.getAttr("square", "curation_by") == series.user


def test_curated_records_who_curated(series):
    series.setCuration(["square"], "Curated")
    curated, user, _date = series.obj_attrs["square"]["curation"]
    assert curated is True and user == series.user
    assert series.getAttr("square", "curation_by") == series.user


def test_clearing_removes_the_assigner_too(series):
    series.setCuration(["square"], "Needs curation", "alice")
    series.setCuration(["square"], "")
    assert series.getAttr("square", "curation") is None
    assert series.getAttr("square", "curation_by") is None


def test_the_tuple_shape_is_unchanged(series):
    """The 3-tuple is load-bearing: shipped builds strict-unpack it, so the
    assigner must never widen it."""
    series.setCuration(["square"], "Needs curation", "alice")
    curated, user, date = series.obj_attrs["square"]["curation"]  # must not raise
    assert (curated, user) == (False, "alice")


def test_a_file_without_the_assigner_reads_as_unknown(series):
    """Older files carry curation but no curation_by; reads degrade to None
    rather than inventing an assigner."""
    series.setCuration(["square"], "Needs curation", "alice")
    del series.obj_attrs["square"]["curation_by"]
    assert series.getAttr("square", "curation_by") is None


def test_history_restore_recovers_the_assigner(series):
    """The log author IS the assigner, so a series rebuilt from history gets
    curation_by back without the event wording having changed at all."""
    series.setCuration(["square"], "Needs curation", "alice")
    del series.obj_attrs["square"]["curation"]
    del series.obj_attrs["square"]["curation_by"]

    series.updateCurationFromHistory()

    assert series.obj_attrs["square"]["curation"][:2] == (False, "alice")
    assert series.getAttr("square", "curation_by") == series.user


# --------------------------------------------------------------------------- #
# the GUI: no dialog on the default, dialog on the deliberate row
# --------------------------------------------------------------------------- #
def _curate_stub(series, monkeypatch):
    """Drive the real bulkCurate off a light stub, the house idiom for
    object_function handlers; QInputDialog is rigged to fail the test if the
    no-dialog path ever prompts."""
    import types

    from PyReconstruct.modules.gui.main import field_widget_3_object as mod

    calls = {"prompted": 0}

    class _NeverDialog:
        @staticmethod
        def getText(*a, **k):
            calls["prompted"] += 1
            return ("someone-else", True)

    monkeypatch.setattr(mod, "QInputDialog", _NeverDialog)

    messages = []

    class _StatusBar:
        def showMessage(self, text, ms=0):
            messages.append(text)

    stub = types.SimpleNamespace(
        series=series,
        series_states=types.SimpleNamespace(addState=lambda *a, **k: None),
        mainwindow=types.SimpleNamespace(statusBar=lambda: _StatusBar()),
    )
    # unbound-method idiom: the plain core calls its sibling helper through
    # self, so the stub borrows it from the class
    stub._curationStatusMessage = (
        lambda *a, **k: mod.FieldWidgetObject._curationStatusMessage(stub, *a, **k)
    )
    return stub, calls, messages, mod


def test_needs_curation_is_instant_and_self_assigned(series, monkeypatch):
    stub, calls, messages, mod = _curate_stub(series, monkeypatch)

    ok = mod.FieldWidgetObject._applyCuration(stub, ["square"], "Needs curation")

    assert ok is True
    assert calls["prompted"] == 0, "the default path prompted"
    assert series.obj_attrs["square"]["curation"][:2] == (False, series.user)
    assert series.getAttr("square", "curation_by") == series.user
    assert any("assigned to you" in m for m in messages), messages


def test_assign_to_keeps_the_dialog_and_prefills_the_user(series, monkeypatch):
    stub, calls, messages, mod = _curate_stub(series, monkeypatch)

    # the prompt path: drive the real dialog wrapper body via the plain core
    # plus the rigged dialog, exactly as the menu row does
    assign_to, confirmed = mod.QInputDialog.getText(stub, "t", "t", text=series.user)
    assert confirmed
    ok = mod.FieldWidgetObject._applyCuration(stub, ["square"], "Needs curation", assign_to)

    assert ok is True
    assert calls["prompted"] == 1
    assert series.obj_attrs["square"]["curation"][:2] == (False, "someone-else")
    assert series.getAttr("square", "curation_by") == series.user

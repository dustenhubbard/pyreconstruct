"""Regression test for exportToZarr crashing on a single-section series.

exportToZarr built its dialog with all_sections[1] as the default "From
section" value. A series with one image has all_sections == [0], so the [1]
access raised IndexError before the dialog was even shown. The export menu
wires straight to this method with no precondition, so it crashed immediately
on a 1-section series. Exercised against a duck-typed stub with the
module-level collaborators monkeypatched.
"""
import types

from PyReconstruct.modules.gui.main import main_window as mw


def _patch_common(monkeypatch, captured):
    monkeypatch.setattr(mw, "modules_available", lambda *a, **k: True)
    monkeypatch.setattr(mw, "notify", lambda *a, **k: None)

    def fake_get(self, structure, *a, **k):
        captured["structure"] = structure
        return (None, False)  # confirmed=False -> method returns after building

    monkeypatch.setattr(mw, "QuickDialog", types.SimpleNamespace(get=fake_get))


def _stub(sections):
    return types.SimpleNamespace(
        series=types.SimpleNamespace(
            sections=sections,
            object_groups=types.SimpleNamespace(getGroupList=lambda: []),
        )
    )


def test_export_to_zarr_single_section_does_not_crash(monkeypatch):
    captured = {}
    _patch_common(monkeypatch, captured)

    mw.MainWindow.exportToZarr(_stub({0: "s.0"}))  # must not raise IndexError

    # the "From section" default falls back to the only available section
    from_field, to_field = captured["structure"][0][1], captured["structure"][0][3]
    assert from_field == ("int", 0)
    assert to_field == ("int", 0)


def test_export_to_zarr_multi_section_default_unchanged(monkeypatch):
    """With >= 2 sections the default "From section" is still index 1 (the
    historical behavior) -- the clamp only affects the single-section case."""
    captured = {}
    _patch_common(monkeypatch, captured)

    mw.MainWindow.exportToZarr(_stub({0: "s.0", 1: "s.1", 2: "s.2"}))

    assert captured["structure"][0][1] == ("int", 1)
    assert captured["structure"][0][3] == ("int", 2)

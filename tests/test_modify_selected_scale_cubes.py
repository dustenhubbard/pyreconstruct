"""Regression test for modifySelected crashing on multiple scale cubes.

When more than one scale cube is selected, modifySelected sets side_len=None
(no common value) and then built the dialog with round(side_len, 4), i.e.
round(None, 4) -> TypeError, before the dialog opened. The sibling color /
opacity / outline fields already pass None directly to QuickDialog, so the edge
length should too. Reachable by selecting all (which selects every cube) and
opening Edit attributes. Exercised against a duck-typed stub.
"""
import types

from PyReconstruct.modules.gui.popup import custom_plotter as cp


def _patch_dialog(monkeypatch, captured):
    def fake_get(parent, structure, *a, **k):
        captured["structure"] = structure
        return ([], False)  # confirmed=False -> method returns after building

    monkeypatch.setattr(cp, "QuickDialog", types.SimpleNamespace(get=fake_get))


def test_multiple_scale_cubes_do_not_crash(monkeypatch):
    captured = {}
    _patch_dialog(monkeypatch, captured)

    stub = types.SimpleNamespace(
        selected=[
            types.SimpleNamespace(type="scale_cube"),
            types.SimpleNamespace(type="scale_cube"),
        ]
    )

    cp.VPlotter.modifySelected(stub)  # must not raise TypeError

    # no common edge length -> the field default is None, like the other fields
    assert captured["structure"][0][1] == ("float", None)


def test_single_scale_cube_default_preserved(monkeypatch):
    captured = {}
    _patch_dialog(monkeypatch, captured)

    cube = types.SimpleNamespace(
        type="scale_cube",
        getSideLength=lambda: 1.23456,
        color="r",
        alpha=0.5,
        msh=types.SimpleNamespace(lw=lambda: 2),
    )
    stub = types.SimpleNamespace(selected=[cube])

    cp.VPlotter.modifySelected(stub)

    assert captured["structure"][0][1] == ("float", 1.2346)

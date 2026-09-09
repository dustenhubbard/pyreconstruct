"""A scale cube keeps its edge length field when other objects share the
selection, and the hover text states the cube's current size.

The lab hit both in September 2026: with a trace object and the cube both
selected, Edit attributes opened a dialog titled "Scale Cube" that offered
only color and opacity, and nothing in the scene said what size the cube
was. Exercised against duck-typed stubs like test_modify_selected_scale_cubes.
"""
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyReconstruct.modules.gui.popup import custom_plotter as cp


def _patch_dialog(monkeypatch, captured, response=None, confirmed=False):
    def fake_get(parent, structure, title, *a, **k):
        captured["structure"] = structure
        captured["title"] = title
        return (response if response is not None else [], confirmed)

    monkeypatch.setattr(cp, "QuickDialog", types.SimpleNamespace(get=fake_get))


def make_cube(side, log):
    return types.SimpleNamespace(
        type="scale_cube",
        color="r",
        alpha=1.0,
        getSideLength=lambda: side,
        msh=types.SimpleNamespace(scale=lambda f: log.append(("cube", f))),
        setColor=lambda c: None,
        setAlpha=lambda a, s=None: None,
    )


def make_object(log):
    return types.SimpleNamespace(
        type="object",
        color="g",
        alpha=0.5,
        msh=types.SimpleNamespace(scale=lambda f: log.append(("object", f))),
        setColor=lambda c: None,
        setAlpha=lambda a, s=None: None,
    )


def make_plotter(*selected):
    return types.SimpleNamespace(
        selected=list(selected),
        series=None,
        saveState=lambda: None,
        updateSelected=lambda: None,
        render=lambda: None,
    )


def test_cube_plus_object_offers_the_edge_length_first(monkeypatch):
    captured, log = {}, []
    _patch_dialog(monkeypatch, captured)

    cp.VPlotter.modifySelected(make_plotter(make_cube(2.0, log), make_object(log)))

    assert captured["structure"][0] == ["Edge length (μm):", ("float", 2.0)]
    assert [row[0] for row in captured["structure"]] == [
        "Edge length (μm):", "Color:", "Opacity (0-1):",
    ]
    assert captured["title"] == "Selected objects"


def test_a_new_length_rescales_the_cubes_only(monkeypatch):
    captured, log = {}, []
    _patch_dialog(monkeypatch, captured, response=[3.0, None, None], confirmed=True)

    cp.VPlotter.modifySelected(make_plotter(make_cube(2.0, log), make_object(log)))

    assert log == [("cube", 1.5)]


def test_cubes_of_different_sizes_leave_the_default_blank(monkeypatch):
    captured, log = {}, []
    _patch_dialog(monkeypatch, captured)

    cp.VPlotter.modifySelected(
        make_plotter(make_cube(1.0, log), make_cube(2.0, log), make_object(log))
    )

    assert captured["structure"][0] == ["Edge length (μm):", ("float", None)]


def test_no_cube_in_the_selection_means_no_length_field(monkeypatch):
    captured, log = {}, []
    _patch_dialog(monkeypatch, captured)

    cp.VPlotter.modifySelected(make_plotter(make_object(log), make_object(log)))

    assert [row[0] for row in captured["structure"]] == ["Color:", "Opacity (0-1):"]


def test_hover_over_the_cube_states_its_edge_length():
    cube = types.SimpleNamespace(
        name="Scale Cube", type="scale_cube", series_fp="/tmp/s.jser",
        getSideLength=lambda: 2.0,
    )
    shown = []
    plotter = types.SimpleNamespace(
        objs={"mesh": cube},
        series=types.SimpleNamespace(jser_fp="/tmp/s.jser"),
        getFieldCoords=lambda msh, pt: (0.5, 0.25, 7),
        pos_text=types.SimpleNamespace(text=shown.append),
        render=lambda: None,
    )
    event = types.SimpleNamespace(actor="mesh", picked3d=(0, 0, 0))

    cp.VPlotter.mouseMoveEvent(plotter, event)

    assert shown == ["Scale Cube\nsection 7\nx=0.500 y=0.250\nedge 2.000 um"]

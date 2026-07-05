"""Regression test for setFocalPointToSelected with no selection.

setFocalPointToSelected computed ``sum(centers) / len(centers)`` with no
empty-selection guard. With nothing selected, centers is [], so this is 0 / 0
-> ZeroDivisionError. The "Center on selected" action ("F") is bound directly
to this method with no precondition, and every sibling selection method
(translateSelected, rotateSelected, removeSelected, ...) opens with
``if not self.selected: return`` -- this one was the lone omission. Exercised
against a duck-typed stub; no real vedo Plotter is constructed.
"""
import types

import numpy as np

from PyReconstruct.modules.gui.popup import custom_plotter as cp


def test_empty_selection_is_noop():
    calls = []
    stub = types.SimpleNamespace(
        selected=[],
        camera=types.SimpleNamespace(SetFocalPoint=lambda c: calls.append(c)),
        render=lambda: None,
    )

    cp.VPlotter.setFocalPointToSelected(stub)  # must not raise ZeroDivisionError

    assert calls == [], "focal point must not be set when nothing is selected"


def test_focal_point_is_average_of_centers():
    calls = []
    stub = types.SimpleNamespace(
        selected=[
            types.SimpleNamespace(center=(0.0, 0.0, 0.0)),
            types.SimpleNamespace(center=(2.0, 2.0, 2.0)),
        ],
        camera=types.SimpleNamespace(SetFocalPoint=lambda c: calls.append(c)),
        render=lambda: None,
    )

    cp.VPlotter.setFocalPointToSelected(stub)

    assert len(calls) == 1
    assert tuple(np.asarray(calls[0])) == (1.0, 1.0, 1.0)

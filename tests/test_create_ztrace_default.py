"""Regression test for createZtrace's mutable default argument.

Series.createZtrace declared ``z_points : list = []`` and appended to it in
place while building a ztrace from an existing object. Because a default
argument is evaluated once and shared across calls, the SECOND from-object
ztrace created in a process reused the first one's accumulated points: the
``if not z_points`` checks (name suffix, point generation) all saw a non-empty
list, so the new ztrace got the wrong name (no ``_zlen`` suffix) and aliased the
previous object's points instead of its own.

createZtrace is invoked once per object name with no z_points by
field_widget_3_object.createZtrace (the 'On contour midpoints' / 'From trace
sequence' context-menu actions) and by checker.py, so creating ztraces for two
objects in a row triggers it. The method is exercised against duck-typed stubs
so no real Series / Qt is required; a real Ztrace is constructed.
"""
import types

from PyReconstruct.modules.datatypes.series import Series


class _Contour:
    def __init__(self, midpoint):
        self._mp = midpoint

    def getMidpoint(self):
        return self._mp


def _make_series_stub():
    # object A spans sections 0 and 1; object B is only on section 0, with a
    # distinct midpoint, so the two ztraces must differ in name and points.
    sec0 = types.SimpleNamespace(
        contours={"A": _Contour((0.0, 0.0)), "B": _Contour((5.0, 5.0))}
    )
    sec1 = types.SimpleNamespace(contours={"A": _Contour((1.0, 1.0))})
    sections = [(0, sec0), (1, sec1)]

    stub = types.SimpleNamespace(
        ztraces={},
        modified_ztraces=set(),
        alignment="current_align",
    )
    stub.enumerateSections = lambda message=None: iter(sections)
    stub.getAttr = lambda name, key: "obj_align"
    stub.setAttr = lambda name, key, val, ztrace=False: None
    stub.addLog = lambda *a, **k: None
    return stub


def test_second_from_object_ztrace_is_independent():
    stub = _make_series_stub()

    Series.createZtrace(stub, "A", cross_sectioned=True)
    Series.createZtrace(stub, "B", cross_sectioned=True)

    # both must be named with the _zlen suffix (the from-object branch)
    assert "A_zlen" in stub.ztraces
    assert "B_zlen" in stub.ztraces, "second ztrace lost its _zlen suffix"
    assert "B" not in stub.ztraces

    # each must carry only its own object's midpoints, not the other's
    assert stub.ztraces["A_zlen"].points == [(0.0, 0.0, 0), (1.0, 1.0, 1)]
    assert stub.ztraces["B_zlen"].points == [(5.0, 5.0, 0)], (
        "second ztrace aliased the first object's points"
    )

    # and they must not share the same underlying list object
    assert stub.ztraces["A_zlen"].points is not stub.ztraces["B_zlen"].points


def test_explicit_points_use_plain_name():
    """Passing z_points explicitly (the field-tracing path) keeps the bare name
    and the provided points -- the fix must not disturb this valid caller."""
    stub = _make_series_stub()

    pts = [(2.0, 2.0, 0), (3.0, 3.0, 1)]
    Series.createZtrace(stub, "traced", cross_sectioned=False, z_points=pts)

    assert "traced" in stub.ztraces
    assert "traced_zlen" not in stub.ztraces
    assert stub.ztraces["traced"].points == pts

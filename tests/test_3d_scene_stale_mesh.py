"""Stale-mesh tracking for the 3D scene.

When an object's 2D traces are edited while its reconstruction is open in the
3D scene, the scene used to keep showing the old mesh until the object was
manually removed and re-added. The fix marks the affected scene objects STALE
at edit time (cheap set bookkeeping, funneled through TableManager) and
regenerates only the stale meshes when the 3D window is next focused (or via
its Scene > Refresh edited objects action).

These tests pin the headless parts of that pipeline:

1. ``SceneObjectList`` stale bookkeeping (mark / mark-all / pop / removal).
2. ``partitionExisting`` -- splitting stale names into still-in-series
   (regenerate) vs. gone-from-series (remove from scene).
3. ``TableManager`` forwarding -- which edits mark what, and that a missing
   or closed viewer is a no-op.

The vedo/Qt rendering itself is exercised manually; the invalidation logic
is what lives here.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyReconstruct.modules.gui.popup.custom_plotter import (
    SceneObjectList,
    partitionExisting,
)
from PyReconstruct.modules.backend.table.manager import TableManager


SERIES_FP = "/tmp/current.jser"
OTHER_FP = "/tmp/other.jser"


def make_series(fp=SERIES_FP):
    return SimpleNamespace(jser_fp=fp, host_tree=None)


def make_mesh():
    return SimpleNamespace(metadata={})


def make_scene(names_types_fps):
    """Build a SceneObjectList with (name, type, series_fp) entries."""
    scene = SceneObjectList()
    added = {}
    for name, type_str, fp in names_types_fps:
        scene_obj = scene.add(
            make_mesh(), make_series(fp), name, type_str, (255, 0, 0), 1.0
        )
        added[(name, type_str, fp)] = scene_obj
    return scene, added


# --------------------------------------------------------------------------- #
# SceneObjectList stale bookkeeping                                            #
# --------------------------------------------------------------------------- #

def test_mark_and_pop_stale_object():
    scene, added = make_scene([("d001", "object", SERIES_FP)])
    scene.markStale(obj_names=["d001"], series_fp=SERIES_FP)
    assert scene.stale_ids == {added[("d001", "object", SERIES_FP)].id}

    obj_names, ztrace_names = scene.popStale()
    assert obj_names == ["d001"]
    assert ztrace_names == []
    # popping clears the set
    assert scene.stale_ids == set()
    assert scene.popStale() == ([], [])


def test_mark_routes_ztraces_separately():
    scene, _ = make_scene([
        ("d001", "object", SERIES_FP),
        ("zt1", "ztrace", SERIES_FP),
    ])
    scene.markStale(obj_names=["d001"], ztrace_names=["zt1"], series_fp=SERIES_FP)
    obj_names, ztrace_names = scene.popStale()
    assert obj_names == ["d001"]
    assert ztrace_names == ["zt1"]


def test_mark_unknown_name_is_noop():
    scene, _ = make_scene([("d001", "object", SERIES_FP)])
    scene.markStale(obj_names=["not_in_scene"], series_fp=SERIES_FP)
    assert scene.stale_ids == set()


def test_mark_wrong_series_is_noop():
    """Objects loaded from another series must not be marked by current-series edits."""
    scene, _ = make_scene([("d001", "object", OTHER_FP)])
    scene.markStale(obj_names=["d001"], series_fp=SERIES_FP)
    assert scene.stale_ids == set()


def test_mark_does_not_cross_types():
    """An edited ztrace must not mark a same-named object (and vice versa)."""
    scene, added = make_scene([
        ("shared", "object", SERIES_FP),
        ("shared", "ztrace", SERIES_FP),
    ])
    scene.markStale(ztrace_names=["shared"], series_fp=SERIES_FP)
    assert scene.stale_ids == {added[("shared", "ztrace", SERIES_FP)].id}


def test_mark_is_idempotent():
    scene, _ = make_scene([("d001", "object", SERIES_FP)])
    scene.markStale(obj_names=["d001"], series_fp=SERIES_FP)
    scene.markStale(obj_names=["d001"], series_fp=SERIES_FP)
    assert len(scene.stale_ids) == 1
    assert scene.popStale() == (["d001"], [])


def test_mark_accepts_sets_and_none():
    """Callers pass sets (section tracking) or leave a kind unspecified."""
    scene, _ = make_scene([("d001", "object", SERIES_FP)])
    scene.markStale(obj_names={"d001"}, ztrace_names=None, series_fp=SERIES_FP)
    assert scene.popStale() == (["d001"], [])


def test_mark_all_stale_scopes_to_series_and_type():
    scene, added = make_scene([
        ("d001", "object", SERIES_FP),
        ("zt1", "ztrace", SERIES_FP),
        ("d002", "object", OTHER_FP),
        ("Scale Cube", "scale_cube", SERIES_FP),
    ])
    scene.markAllStale(series_fp=SERIES_FP)
    assert scene.stale_ids == {
        added[("d001", "object", SERIES_FP)].id,
        added[("zt1", "ztrace", SERIES_FP)].id,
    }


def test_remove_clears_staleness():
    """Removing a scene object (user delete, or the remove-first leg of a
    regeneration) must drop its stale flag so it is not re-processed."""
    scene, added = make_scene([("d001", "object", SERIES_FP)])
    scene.markStale(obj_names=["d001"], series_fp=SERIES_FP)
    scene.remove(added[("d001", "object", SERIES_FP)])
    assert scene.stale_ids == set()
    assert scene.popStale() == ([], [])


def test_pop_skips_ids_no_longer_in_scene():
    """A stale id whose object vanished is skipped but still cleared."""
    scene, _ = make_scene([("d001", "object", SERIES_FP)])
    scene.stale_ids.add("gone42")
    obj_names, ztrace_names = scene.popStale()
    assert obj_names == []
    assert ztrace_names == []
    assert scene.stale_ids == set()


# --------------------------------------------------------------------------- #
# partitionExisting: regenerate vs. remove-from-scene                          #
# --------------------------------------------------------------------------- #

def test_partition_existing_splits_kept_and_gone():
    series = SimpleNamespace(
        data={"objects": {"d001": {}, "d002": {}}},
        ztraces={"zt1": object()},
    )
    kept_o, kept_z, gone_o, gone_z = partitionExisting(
        ["d001", "deleted_obj", "d002"], ["zt1", "deleted_zt"], series
    )
    assert kept_o == ["d001", "d002"]
    assert gone_o == ["deleted_obj"]
    assert kept_z == ["zt1"]
    assert gone_z == ["deleted_zt"]


def test_partition_existing_empty_input():
    series = SimpleNamespace(data={"objects": {}}, ztraces={})
    assert partitionExisting([], [], series) == ([], [], [], [])


# --------------------------------------------------------------------------- #
# TableManager forwarding                                                      #
# --------------------------------------------------------------------------- #

class ViewerStub:
    def __init__(self, is_closed=False):
        self.is_closed = is_closed
        self.mark_calls = []
        self.mark_all_calls = 0

    def markStale(self, obj_names=None, ztrace_names=None):
        self.mark_calls.append((obj_names, ztrace_names))

    def markAllStale(self):
        self.mark_all_calls += 1


def make_manager(viewer):
    series = SimpleNamespace(
        modified_ztraces={"zt1"},
        clearTracking=lambda: None,
    )
    section = SimpleNamespace(
        tformsModified=lambda scaling_only=False: False,
        getAllModifiedNames=lambda: {"traced_obj"},
        contours={},
        clearTracking=lambda: None,
    )
    mainwindow = SimpleNamespace(viewer=viewer, saveAllData=lambda: None)
    return TableManager(series, section, None, mainwindow)


def test_update_objects_forwards_explicit_names():
    viewer = ViewerStub()
    manager = make_manager(viewer)
    manager.updateObjects(["d001", "d002"])
    assert viewer.mark_calls == [(["d001", "d002"], None)]


def test_update_objects_forwards_section_tracking():
    """A field edit calls updateObjects() with no names; the modified names
    come from the section's tracking -- exactly what must reach the scene."""
    viewer = ViewerStub()
    manager = make_manager(viewer)
    manager.updateObjects()
    assert viewer.mark_calls == [({"traced_obj"}, None)]


def test_update_ztraces_forwards_series_tracking():
    viewer = ViewerStub()
    manager = make_manager(viewer)
    manager.updateZtraces()
    assert viewer.mark_calls == [(None, {"zt1"})]


def test_recreate_tables_marks_all():
    viewer = ViewerStub()
    manager = make_manager(viewer)
    manager.recreateTables()
    assert viewer.mark_all_calls == 1
    assert viewer.mark_calls == []


def test_no_viewer_is_noop():
    manager = make_manager(None)
    manager.updateObjects(["d001"])  # must not raise
    manager.updateZtraces()
    manager.recreateTables()


def test_closed_viewer_is_not_notified():
    viewer = ViewerStub(is_closed=True)
    manager = make_manager(viewer)
    manager.updateObjects(["d001"])
    manager.updateZtraces()
    manager.recreateTables()
    assert viewer.mark_calls == []
    assert viewer.mark_all_calls == 0


# --------------------------------------------------------------------------- #
# Container: window activation triggers the refresh                            #
# --------------------------------------------------------------------------- #

def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _make_fake_plotter(auto_refresh=True):
    """A stand-in plotter whose auto-refresh option can be toggled."""
    from PySide6.QtWidgets import QWidget

    class FakePlotter(QWidget):
        plt = object()  # marks construction as finished

        def __init__(self):
            super().__init__()
            self.refresh_calls = 0
            self.series = SimpleNamespace(
                getOption=lambda name: auto_refresh
            )

        def refreshStale(self):
            self.refresh_calls += 1

    return FakePlotter()


def test_window_activate_calls_refresh_stale():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEvent
    from PyReconstruct.modules.gui.popup.custom_plotter import Container

    _qapp()

    container = Container()
    plotter = _make_fake_plotter(auto_refresh=True)
    container.setCentralWidget(plotter)

    QApplication.sendEvent(container, QEvent(QEvent.Type.WindowActivate))
    assert plotter.refresh_calls == 1

    # unrelated events do not trigger a refresh
    QApplication.sendEvent(container, QEvent(QEvent.Type.WindowDeactivate))
    assert plotter.refresh_calls == 1


def test_window_activate_skips_refresh_when_auto_refresh_off():
    """With auto-refresh disabled, focusing the window must NOT regenerate;
    the user drives the refresh manually instead."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEvent
    from PyReconstruct.modules.gui.popup.custom_plotter import Container

    _qapp()

    container = Container()
    plotter = _make_fake_plotter(auto_refresh=False)
    container.setCentralWidget(plotter)

    QApplication.sendEvent(container, QEvent(QEvent.Type.WindowActivate))
    assert plotter.refresh_calls == 0


def test_window_activate_ignores_half_constructed_plotter():
    """The central widget is set before CustomPlotter.__init__ finishes; an
    activation arriving then (no ``plt`` yet) must be a no-op."""
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import QEvent
    from PyReconstruct.modules.gui.popup.custom_plotter import Container

    _qapp()

    container = Container()
    container.setCentralWidget(QWidget())  # no plt, no refreshStale
    QApplication.sendEvent(container, QEvent(QEvent.Type.WindowActivate))  # must not raise

"""3D settings rebuild meshes without changing unrelated scene objects."""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QRadioButton, QSlider

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from test_3d_scene_follows_open_series import _mesh, _viewer

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def isolated_options(main_window, local_series_settings):
    local_series_settings(main_window)


def edit_options(changes, accept=True):
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, AllOptionsDialog)
    group = dialog.all_widgets["smoothing_3D"]
    if "3D_xy_res" in changes:
        group.findChild(QSlider).setValue(changes["3D_xy_res"])
    if "3D_smoothing" in changes:
        next(b for b in group.findChildren(QRadioButton)
             if b.text() == "Taubin").setChecked(True)
    for index, key in enumerate(("smoothing_iterations", "screenshot_res")):
        if key in changes:
            group.findChildren(QLineEdit)[index].setText(str(changes[key]))
    if "3D_auto_refresh" in changes:
        group.findChild(QCheckBox).setChecked(changes["3D_auto_refresh"])
    dialog.accept() if accept else dialog.reject()


def populate(window, monkeypatch):
    viewer, launched = _viewer(window, monkeypatch)

    def recreate_cube(*args, **kwargs):
        pytest.fail("recreated a scale cube during mesh reload")

    monkeypatch.setattr(viewer.plt, "toggleScaleCube", recreate_cube)
    names = sorted(window.series.data["objects"])[:2]
    objects = [viewer.plt.objs.add(_mesh(), window.series, n, "object", (12, 34, 56), .4)
               for n in names]
    cube = viewer.plt.objs.add(_mesh(), window.series, "Scale Cube", "scale_cube", (1, 1, 1), 1)
    return viewer, launched, objects, cube


@pytest.mark.parametrize("changes", [
    {"3D_xy_res": 80}, {"3D_smoothing": "taubin"}, {"smoothing_iterations": 7},
])
def test_mesh_settings_rebuild_open_objects(main_window, monkeypatch, changes):
    viewer, launched, objects, cube = populate(main_window, monkeypatch)
    main_window.series.setOption("3D_auto_refresh", False)
    QTimer.singleShot(0, lambda: edit_options(changes))
    main_window.allOptions()
    assert launched == [(main_window.series, [o.name for o in objects])]
    assert viewer.plt.objs[cube.id] is cube


@pytest.mark.parametrize("changes,accept", [
    ({"screenshot_res": 600}, True), ({"3D_auto_refresh": False}, True),
    ({}, True), ({"3D_xy_res": 80}, False),
])
def test_other_options_and_cancel_do_not_rebuild(main_window, monkeypatch, changes, accept):
    viewer, launched, objects, cube = populate(main_window, monkeypatch)
    QTimer.singleShot(0, lambda: edit_options(changes, accept))
    main_window.allOptions()
    assert launched == []
    assert all(viewer.plt.objs[o.id] is o for o in [*objects, cube])


@pytest.mark.parametrize("selected", [False, True])
def test_reload_leaves_unselected_objects_and_scale_cube_untouched(main_window, monkeypatch, selected):
    viewer, launched, objects, cube = populate(main_window, monkeypatch)
    viewer.plt.selected = objects[:1] if selected else []
    untouched = [*objects[1:], cube] if selected else [*objects, cube]
    for obj in untouched:
        monkeypatch.setattr(obj, "setAttrs", lambda *args: pytest.fail("changed an unselected object"))
    viewer.reload()
    assert launched == ([(main_window.series, [objects[0].name])] if selected else [])
    assert all(viewer.plt.objs[o.id] is o for o in untouched)


@pytest.fixture
def scene_menu(main_window, monkeypatch, qtbot):
    """Build the real scene window and menus without an OpenGL renderer."""
    from unittest.mock import Mock
    from PySide6.QtWidgets import QWidget
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    plotter = Mock(actors=[], selected=[])
    plotter.objs = cp.SceneObjectList()
    monkeypatch.setattr(cp, "VPlotter", lambda *a, **k: plotter)
    monkeypatch.setattr(cp.QVTKRenderWindowInteractor, "__init__", QWidget.__init__)
    def missing_attribute(self, name):
        raise AttributeError(name)

    monkeypatch.setattr(cp.QVTKRenderWindowInteractor, "__getattr__", missing_attribute)
    for event in ("paintEvent", "resizeEvent", "closeEvent", "keyReleaseEvent",
                  "enterEvent", "leaveEvent", "mouseMoveEvent", "mousePressEvent",
                  "mouseReleaseEvent", "wheelEvent"):
        monkeypatch.setattr(cp.CustomPlotter, event, getattr(QWidget, event))
    viewer = cp.CustomPlotter(main_window)
    qtbot.addWidget(viewer.container)
    yield viewer
    main_window.viewer = None


def test_scene_settings_opens_existing_controls(scene_menu, main_window, qtbot):
    viewer = scene_menu
    observed = []

    def check_and_edit():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, AllOptionsDialog)
        assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "View"
        group = dialog.all_widgets["smoothing_3D"]
        assert group.isVisible()
        observed.append(True)
        edit_options({"3D_xy_res": 80, "3D_smoothing": "taubin",
                      "smoothing_iterations": 7, "screenshot_res": 600,
                      "3D_auto_refresh": False})

    action = viewer.settings_act
    QTimer.singleShot(0, check_and_edit)
    action.trigger()
    assert observed == [True]
    assert main_window.series.getOption("screenshot_res") == 600
    assert main_window.series.getOption("3D_auto_refresh") is False
    dialog = AllOptionsDialog(main_window, main_window.series)
    qtbot.addWidget(dialog)
    group = dialog.all_widgets["smoothing_3D"]
    assert group.findChild(QSlider).value() == 80
    assert next(b for b in group.findChildren(QRadioButton) if b.text() == "Taubin").isChecked()
    assert group.findChildren(QLineEdit)[0].text() == "7"
    assert group.findChildren(QLineEdit)[1].text() == "600"
    assert not group.findChild(QCheckBox).isChecked()


@pytest.mark.filterwarnings("ignore:Function.*setActiveWindow.*:DeprecationWarning")
def test_reload_shortcut_runs_only_in_focused_window(scene_menu, main_window, qtbot):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    viewer = scene_menu
    calls = []
    viewer.reload_act.triggered.connect(lambda: calls.append("scene"))
    # Disconnect the actual edits; retain both windows' real shortcut owners.
    viewer.reload_act.triggered.disconnect(viewer.reload)
    main_window.smoothtraces_act.triggered.disconnect()
    main_window.smoothtraces_act.triggered.connect(lambda: calls.append("field"))
    viewer.container.raise_()
    viewer.container.activateWindow()
    QApplication.setActiveWindow(viewer.container)
    viewer.setFocus()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is viewer.container)
    QTest.keySequence(viewer, QKeySequence("Ctrl+Shift+R"))
    assert calls == ["scene"]
    main_window.activateWindow()
    QApplication.setActiveWindow(main_window)
    main_window.field.setFocus()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window)
    QTest.keySequence(main_window.field, QKeySequence("Ctrl+Shift+R"))
    assert calls == ["scene", "field"]


def test_reload_groups_selected_meshes_by_source_and_preserves_attributes(main_window, monkeypatch):
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    viewer, launched, objects, cube = populate(main_window, monkeypatch)
    other = SimpleNamespace(jser_fp="/other.jser", host_tree=None)
    foreign = viewer.plt.objs.add(_mesh(), other, objects[0].name, "object", (8, 9, 10), .7)
    ztrace = viewer.plt.objs.add(_mesh(), other, "path", "ztrace", (9, 8, 7), .6)
    objects[0].translate(2, 3, 4)
    expected = objects[0].getExportDict()
    viewer.plt.selected = [objects[0], foreign, ztrace, cube]
    workers = []

    class Pool:
        def createWorker(self, fn, series, objects, ztraces, **kwargs):
            workers.append((series, objects, ztraces))
            return SimpleNamespace(signals=SimpleNamespace(result=SimpleNamespace(connect=lambda f: None)))

        def startAll(self, **kwargs):
            pass

    monkeypatch.setattr(cp, "ThreadPoolProgBar", Pool)
    viewer.reload()
    assert len(workers) == 2
    source, reloaded, paths = workers[0]
    assert source is main_window.series
    assert reloaded == [expected]
    assert paths == []
    source, reloaded, paths = workers[1]
    assert source == "/other.jser"
    assert reloaded == [foreign.getExportDict()]
    assert paths == [ztrace.getExportDict()]
    assert viewer.plt.objs[objects[1].id] is objects[1]
    assert viewer.plt.objs[cube.id] is cube


@pytest.mark.parametrize("trigger", ["settings", "reload"])
@pytest.mark.parametrize("missing_type", ["object", "ztrace"])
def test_rebuild_with_deleted_source_preserves_valid_meshes(
    main_window, monkeypatch, trigger, missing_type
):
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    viewer, _, objects, cube = populate(main_window, monkeypatch)
    series = main_window.series
    series.setOption("3D_auto_refresh", False)
    for obj in objects:
        series.setAttr(obj.name, "3D_mode", "contours")
        obj.translate(2, 3, 4)
    expected = {obj.name: obj.getExportDict() for obj in objects}
    for attrs in expected.values():
        attrs.pop("id")
    missing = viewer.plt.objs.add(
        _mesh(), series, "deleted_source", missing_type, (9, 8, 7), .6
    )
    assert missing.name not in series.data["objects"]
    assert missing.name not in series.ztraces
    viewer.plt.selected = [*objects, missing]
    notices = []
    monkeypatch.setattr(cp, "notify", notices.append)
    monkeypatch.setattr(cp, "notifyConfirm", lambda *a, **k: notices.append(a) or False)
    workers = []

    class Pool:
        def createWorker(self, fn, source, objs, ztraces, **kwargs):
            workers.append(([d["name"] for d in objs], [d["name"] for d in ztraces]))
            self.run = lambda: fn(source, objs, ztraces)
            return SimpleNamespace(signals=SimpleNamespace(
                result=SimpleNamespace(connect=lambda slot: setattr(self, "place", slot))
            ))

        def startAll(self, **kwargs):
            self.place(self.run())

    monkeypatch.setattr(cp, "ThreadPoolProgBar", Pool)
    if trigger == "settings":
        QTimer.singleShot(0, lambda: edit_options({"3D_xy_res": 80}))
        main_window.allOptions()
    else:
        viewer.reload()

    assert workers == [([obj.name for obj in objects], [])]
    assert notices == []
    assert viewer.plt.objs.search(missing.name, missing_type, series.jser_fp) is None
    for old in objects:
        rebuilt = viewer.plt.objs.search(old.name, "object", series.jser_fp)
        assert rebuilt is not None
        assert rebuilt is not old
        attrs = rebuilt.getExportDict()
        attrs.pop("id")
        assert attrs == expected[old.name]
    assert viewer.plt.objs[cube.id] is cube


@pytest.mark.parametrize("missing_type", ["object", "ztrace"])
def test_rebuild_with_only_deleted_sources_leaves_scale_cube(
    main_window, monkeypatch, missing_type
):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    viewer, launched, objects, cube = populate(main_window, monkeypatch)
    viewer.plt.removeFromScene([obj.name for obj in objects], [], save_state=False)
    missing = viewer.plt.objs.add(
        _mesh(), main_window.series, "deleted_source", missing_type, (9, 8, 7), .6
    )
    notices = []
    monkeypatch.setattr(cp, "notify", notices.append)
    viewer.rebuildObjects([missing, cube])
    assert launched == []
    assert list(viewer.plt.objs.values()) == [cube]
    assert notices == []


@pytest.mark.parametrize("trigger", ["settings", "reload"])
@pytest.mark.parametrize("failure", ["missing", "invalid", "generation"])
def test_failed_rebuild_keeps_displayed_meshes(
    main_window, monkeypatch, tmp_path, trigger, failure
):
    from types import SimpleNamespace
    from PyReconstruct.modules.backend.threading.threading import Worker
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    viewer, _, objects, cube = populate(main_window, monkeypatch)
    series = main_window.series
    series.setOption("3D_auto_refresh", False)
    for obj in objects:
        series.setAttr(obj.name, "3D_mode", "contours")
        obj.translate(2, 3, 4)
    foreign_path = tmp_path / "unavailable.jser"
    if failure == "invalid":
        foreign_path.write_text("invalid JSON")
    other = SimpleNamespace(jser_fp=str(foreign_path), host_tree=None)
    foreign = [
        viewer.plt.objs.add(_mesh(), other, objects[0].name, "object", (8, 9, 10), .7),
        viewer.plt.objs.add(_mesh(), other, "path", "ztrace", (9, 8, 7), .6),
    ]
    for obj in foreign:
        obj.translate(5, 6, 7)
    expected = {obj.id: obj.getExportDict() for obj in [*objects, *foreign]}
    viewer.plt.selected = [*objects, *foreign, cube]
    failures = []
    visible_during_generation = []

    class Pool:
        def createWorker(self, fn, source, objs, ztraces, **kwargs):
            def generate():
                if source == str(foreign_path):
                    # Existing meshes remain visible while their replacements run.
                    visible_during_generation.extend(
                        viewer.plt.objs[obj.id] is obj for obj in foreign
                    )
                    if failure == "generation":
                        raise RuntimeError("mesh generation failed")
                return fn(source, objs, ztraces)

            self.worker = Worker(generate)
            self.worker.signals.error.connect(lambda error: failures.append(error[0]))
            return self.worker

        def startAll(self, **kwargs):
            self.worker.run()

    monkeypatch.setattr(cp, "ThreadPoolProgBar", Pool)
    if trigger == "settings":
        QTimer.singleShot(0, lambda: edit_options({"3D_xy_res": 80}))
        main_window.allOptions()
    else:
        viewer.reload()

    from PyReconstruct.modules.datatypes.series import SeriesOpenError
    assert failures == [{"missing": FileNotFoundError, "invalid": SeriesOpenError,
                         "generation": RuntimeError}[failure]]
    assert visible_during_generation == [True, True]
    for obj in foreign:
        assert viewer.plt.objs.search(obj.name, obj.type, str(foreign_path)) is obj
        assert obj.getExportDict() == expected[obj.id]
        assert obj in viewer.plt.selected
    for old in objects:
        rebuilt = viewer.plt.objs.search(old.name, old.type, series.jser_fp)
        assert rebuilt is not None and rebuilt is not old
        attrs = rebuilt.getExportDict()
        attrs.pop("id")
        old_attrs = expected[old.id].copy()
        old_attrs.pop("id")
        assert attrs == old_attrs
    assert viewer.plt.objs[cube.id] is cube
    assert len(list(viewer.plt.objs.values())) == 5

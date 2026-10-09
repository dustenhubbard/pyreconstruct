"""The 3D scene follows the open series through `File` > `Save as...`.

Each scene object keeps the path of the series it came from in `series_fp`,
and the scene tells the open series' objects apart by comparing that path with
`series.jser_fp`. Save As changes `jser_fp`, so without an update every object
from the open series looks like it came from another one: `Revert selected...`
reads the colors last saved in the old file (or nothing, if it is gone), and a
double-click no longer jumps to the object in the field.

The real `CustomPlotter.seriesMoved`, `VPlotter.revertSelectedColor` and
`VPlotter.leftButtonClickEvent` run on stand-ins that carry the attributes they
read; building the VTK plotter offscreen is impractical. The window, the Save
As, the series and the scene object list are real.
"""
import types

import pytest
import vedo

pytestmark = pytest.mark.gui


def _mesh():
    return vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]])


def _viewer(series):
    """A stand-in CustomPlotter holding a real scene object list."""
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    viewer = types.SimpleNamespace(
        is_closed=False,
        series=series,
        undo_states=[],
        redo_states=[],
        plt=types.SimpleNamespace(objs=cp.SceneObjectList()),
    )
    helper = getattr(cp.CustomPlotter, "seriesMoved", None)
    if helper is not None:
        viewer.seriesMoved = types.MethodType(helper, viewer)
    else:  # before the fix, Save As never told the scene anything
        viewer.seriesMoved = lambda *_args: None
    paths = getattr(cp.CustomPlotter, "seriesPaths", None)
    if paths is not None:
        viewer.seriesPaths = types.MethodType(paths, viewer)
    return viewer


def _plotter(series, objs, selected=(), mainwindow=None):
    """A stand-in VPlotter for the methods under test."""
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    fake = types.SimpleNamespace(
        series=series, objs=objs, selected=list(selected),
        mainwindow=mainwindow, click_time=None,
        saveState=lambda: None, render=lambda: None,
        updateSelected=lambda: None,
        getFieldCoords=lambda _msh, _pt: (1.0, 2.0, 3),
    )
    fake._seriesForRevert = types.MethodType(cp.VPlotter._seriesForRevert, fake)
    return fake


def _save_as(window, dialogs, tmp_path):
    dest = tmp_path / "saved_as" / "renamed.jser"
    dest.parent.mkdir()
    dialogs.file_responses.append(str(dest))
    window.saveAsToJser()
    assert window.series.jser_fp == str(dest)
    return str(dest)


def test_revert_after_save_as_reads_the_open_series(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    window = main_window
    series = window.series
    name = sorted(series.data["objects"].keys())[0]
    viewer = _viewer(series)
    monkeypatch.setattr(window, "viewer", viewer)
    obj = viewer.plt.objs.add(_mesh(), series, name, "object", (9, 9, 9), 1)
    old_fp = series.jser_fp

    _save_as(window, main_window_dialogs, tmp_path)

    # recolor the object in the open series only; the old file keeps its colors
    for snum in series.sections:
        section = series.loadSection(snum)
        if name in section.contours:
            for trace in section.contours[name]:
                trace.color = (1, 2, 3)
            section.save()

    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    cp.VPlotter.revertSelectedColor(_plotter(series, viewer.plt.objs, [obj]))

    assert tuple(obj.color) == (1, 2, 3)
    assert obj.series_fp == series.jser_fp != old_fp


def test_double_click_after_save_as_jumps_to_the_object(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    window = main_window
    series = window.series
    name = sorted(series.data["objects"].keys())[0]
    viewer = _viewer(series)
    monkeypatch.setattr(window, "viewer", viewer)
    obj = viewer.plt.objs.add(_mesh(), series, name, "object", (9, 9, 9), 1)

    _save_as(window, main_window_dialogs, tmp_path)

    moves = []
    mainwindow = types.SimpleNamespace(
        field=types.SimpleNamespace(moveTo=lambda *a: moves.append(a)),
        activateWindow=lambda: None,
    )
    fake = _plotter(series, viewer.plt.objs, mainwindow=mainwindow)
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    for t in (1.0, 1.1):
        event = types.SimpleNamespace(time=t, actor=obj.msh, picked3d=(0, 0, 0))
        cp.VPlotter.leftButtonClickEvent(fake, event)

    assert moves == [(3, 1.0, 2.0)]


def test_series_moved_leaves_other_series_alone():
    old_fp, new_fp, other_fp = "/a/old.jser", "/b/new.jser", "/c/other.jser"
    open_series = types.SimpleNamespace(jser_fp=old_fp, host_tree="open tree")
    other_series = types.SimpleNamespace(jser_fp=other_fp, host_tree="other tree")
    viewer = _viewer(open_series)
    objs = viewer.plt.objs
    mine = objs.add(types.SimpleNamespace(metadata={}), open_series, "d01",
                    "object", (1, 1, 1), 1)
    theirs = objs.add(types.SimpleNamespace(metadata={}), other_series, "d01",
                      "object", (1, 1, 1), 1)
    viewer.undo_states.append(
        {"scene_objects": {"series_fps": {
            old_fp: {"objects": [{"id": "x"}], "ztraces": []},
            other_fp: {"objects": [{"id": "y"}], "ztraces": []},
        }}}
    )

    viewer.seriesMoved(old_fp, new_fp)

    assert mine.series_fp == new_fp
    assert theirs.series_fp == other_fp
    assert objs.host_trees == {new_fp: "open tree", other_fp: "other tree"}
    assert objs.search("d01", "object", new_fp) is mine
    state = viewer.undo_states[0]["scene_objects"]["series_fps"]
    assert state == {
        new_fp: {"objects": [{"id": "x"}], "ztraces": []},
        other_fp: {"objects": [{"id": "y"}], "ztraces": []},
    }


def _scene_with_other_series(window, tmp_path, series_jser, monkeypatch):
    """The open series and another one in the scene, both with a `d01`.

    The other series is opened and closed the way `From other series...`
    does it, so only its .jser is left on disk.
    """
    import shutil
    from PyReconstruct.modules.datatypes import Series

    other_jser = tmp_path / "other" / "other.jser"
    other_jser.parent.mkdir()
    shutil.copy(series_jser, other_jser)
    other = Series.openJser(str(other_jser))
    other.close()

    series = window.series
    viewer = _viewer(series)
    monkeypatch.setattr(window, "viewer", viewer)
    mine = viewer.plt.objs.add(_mesh(), series, "d01", "object", (1, 1, 1), 1)
    theirs = viewer.plt.objs.add(_mesh(), other, "d01", "object", (2, 2, 2), 1)
    return viewer, mine, theirs, str(other_jser)


def test_save_as_refuses_a_series_in_the_scene(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """Saving over the .jser of another series in the scene would mix the two."""
    window = main_window
    viewer, mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    own_fp = window.series.jser_fp
    with open(other_fp, "rb") as fh:
        other_before = fh.read()

    main_window_dialogs.file_responses.append(other_fp)
    result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    with open(other_fp, "rb") as fh:
        assert fh.read() == other_before
    assert mine.series_fp == own_fp
    assert theirs.series_fp == other_fp
    assert any(
        "other.jser" in text and "3D scene" in text
        for _title, text in main_window_dialogs.message_boxes
    )


def test_save_as_refuses_a_series_only_in_the_undo_history(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """An undo would bring the other series' objects back under this one."""
    window = main_window
    viewer, _mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    viewer.undo_states.append({"scene_objects": viewer.plt.objs.getExportDict()})
    viewer.plt.objs.remove(theirs)
    own_fp = window.series.jser_fp

    main_window_dialogs.file_responses.append(other_fp)
    result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    assert other_fp in viewer.undo_states[0]["scene_objects"]["series_fps"]


def test_save_as_over_itself_with_a_scene_still_saves(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    window = main_window
    _viewer_, mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    own_fp = window.series.jser_fp

    main_window_dialogs.file_responses.append(own_fp)
    result = window.saveAsToJser()

    assert result is None
    assert window.series.jser_fp == own_fp
    assert main_window_dialogs.message_boxes == []
    assert mine.series_fp == own_fp and theirs.series_fp == other_fp


def test_save_as_refuses_a_series_only_in_the_redo_history(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """A redo would bring the other series' objects back under this one."""
    window = main_window
    viewer, _mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    viewer.redo_states.append({"scene_objects": viewer.plt.objs.getExportDict()})
    viewer.plt.objs.remove(theirs)
    own_fp = window.series.jser_fp

    main_window_dialogs.file_responses.append(other_fp)
    result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    assert other_fp in viewer.redo_states[0]["scene_objects"]["series_fps"]


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_save_as_refuses_a_scene_series_linked_to_this_one(
    link, main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """The scene keeps a series opened through a link apart from this one.

    Saving onto the link would move this series to that path and merge the
    two in the scene, though both paths reach the same file.
    """
    import os
    from PyReconstruct.modules.datatypes import Series

    window = main_window
    own_fp = window.series.jser_fp
    link_fp = tmp_path / "linked" / "other.jser"
    link_fp.parent.mkdir()
    try:
        if link == "symlink":
            os.symlink(own_fp, link_fp)
        else:
            os.link(own_fp, link_fp)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"cannot make a {link} here: {e}")
    other = Series.openJser(str(link_fp))
    other.close()

    viewer = _viewer(window.series)
    monkeypatch.setattr(window, "viewer", viewer)
    mine = viewer.plt.objs.add(_mesh(), window.series, "d01", "object", (1, 1, 1), 1)
    theirs = viewer.plt.objs.add(_mesh(), other, "d01", "object", (2, 2, 2), 1)

    main_window_dialogs.file_responses.append(str(link_fp))
    result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    assert mine.series_fp == own_fp
    assert theirs.series_fp == str(link_fp)
    assert any(
        "other.jser" in text and "3D scene" in text
        for _title, text in main_window_dialogs.message_boxes
    )


def test_same_path_matches_a_missing_file_through_a_folder_link(tmp_path):
    """With the file gone, a symlinked folder still names the same path."""
    import os
    from PyReconstruct.modules.gui.main.main_window import _samePath

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        os.symlink(real, alias, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"cannot make a symlink here: {e}")

    assert _samePath(str(alias / "B.jser"), str(real / "B.jser"))
    assert not _samePath(str(alias / "B.jser"), str(real / "C.jser"))


def _volume_ignores_case(folder):
    """Probe inside the folder, not the platform or the folders above it.

    A test folder is ours to write in, so a probe file there answers for
    the folder's own volume.
    """
    import os
    probe = os.path.join(str(folder), "CaseProbe")
    open(probe, "w").close()
    try:
        return os.path.exists(os.path.join(str(folder), "cASEpROBE"))
    finally:
        os.remove(probe)


def test_same_path_ignores_case_for_missing_files_where_the_volume_does(tmp_path):
    """With the file gone, Data/B.jser and data/b.jser still name one file."""
    from PyReconstruct.modules.gui.main.main_window import _samePath

    data = tmp_path / "Data"
    data.mkdir()
    if not _volume_ignores_case(data):
        pytest.skip("this volume is case-sensitive")
    lower = tmp_path / "data"

    assert _samePath(str(data / "B.jser"), str(data / "b.jser"))
    assert _samePath(str(data / "B.jser"), str(lower / "B.jser"))
    assert _samePath(str(data / "B.jser"), str(lower / "b.jser"))
    assert _samePath(str(data / "Sub" / "B.jser"), str(lower / "sub" / "b.jser"))
    assert not _samePath(str(data / "B.jser"), str(data / "C.jser"))
    assert not _samePath(str(data / "B.jser"), str(data / "Sub" / "B.jser"))


def test_save_as_refuses_a_missing_scene_series_spelled_in_other_case(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """Once the other series' .jser is gone, its path in another case is still taken."""
    import os

    window = main_window
    viewer, _mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    if not _volume_ignores_case(os.path.dirname(other_fp)):
        pytest.skip("this volume is case-sensitive")
    os.remove(other_fp)
    own_fp = window.series.jser_fp
    chosen = os.path.join(str(tmp_path), "OTHER", "Other.jser")

    main_window_dialogs.file_responses.append(chosen)
    result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    assert theirs.series_fp == other_fp
    assert not os.path.exists(other_fp)


def _same_both_ways(a, b):
    """_samePath, checked to give the same answer in either order."""
    from PyReconstruct.modules.gui.main.main_window import _samePath
    result = _samePath(a, b)
    assert _samePath(b, a) == result
    return result


def _fake_case_rules(monkeypatch, reject):
    """Make os.stat and os.lstat fail for paths `reject` says do not exist.

    Lets one folder behave as case-sensitive on a volume that is not, the
    way a volume mounted inside another one would.
    """
    import os
    real_stat, real_lstat = os.stat, os.lstat

    def wrap(real):
        def fake(p, *a, **k):
            if isinstance(p, (str, os.PathLike)) and reject(os.fspath(p)):
                raise FileNotFoundError(p)
            return real(p, *a, **k)
        return fake

    monkeypatch.setattr(os, "stat", wrap(real_stat))
    monkeypatch.setattr(os, "lstat", wrap(real_lstat))


def test_case_probe_ignores_a_case_sensitive_folder_above(tmp_path, monkeypatch):
    """A case-insensitive folder below case-sensitive ones still ignores case."""

    data = tmp_path / "Data"
    data.mkdir()
    (data / "Notes.txt").write_text("")
    if not _volume_ignores_case(data):
        pytest.skip("this volume is case-sensitive")
    above = str(tmp_path)

    def reject(p):  # every folder down to tmp_path minds case
        head = p[:len(above)]
        return head != above and head.casefold() == above.casefold()

    with monkeypatch.context() as m:
        _fake_case_rules(m, reject)
        assert _same_both_ways(str(data / "B.jser"), str(data / "b.jser"))
        assert not _same_both_ways(str(data / "B.jser"), str(data / "C.jser"))


def test_case_probe_trusts_a_case_sensitive_folder_below(tmp_path, monkeypatch):
    """A case-sensitive folder inside a case-insensitive one keeps case."""
    import os

    data = tmp_path / "Data"
    data.mkdir()
    (data / "Notes.txt").write_text("")
    inside = str(data) + os.sep
    names = set(os.listdir(data))

    def reject(p):  # names inside Data must match their exact spelling
        if not p.startswith(inside):
            return False
        return p[len(inside):].split(os.sep)[0] not in names

    with monkeypatch.context() as m:
        _fake_case_rules(m, reject)
        assert not _same_both_ways(str(data / "B.jser"), str(data / "b.jser"))


def test_case_probe_judges_an_empty_numeric_folder(tmp_path):
    """An empty 2026 folder has no entry to probe, and still ignores case here."""
    from PyReconstruct.modules.gui.main.main_window import _samePath

    year = tmp_path / "2026"
    year.mkdir()
    if not _volume_ignores_case(year):
        pytest.skip("this volume is case-sensitive")

    assert _samePath(str(year / "B.jser"), str(year / "b.jser"))
    assert not _samePath(str(year / "B.jser"), str(year / "C.jser"))


def _system_says(monkeypatch, answer):
    """Make the system's answer about any folder's case `answer`.

    True: names ignore case (chattr +F on Linux). False: names keep case
    (per-folder case sensitivity on NTFS). None: no answer.
    """
    from PyReconstruct.modules.gui.main import main_window
    monkeypatch.setattr(main_window, "_askFolderCase", lambda folder: answer)


@pytest.mark.parametrize(
    "answer, same", [(True, True), (None, True), (False, False)],
    ids=["folds-case", "cannot-tell", "minds-case"],
)
@pytest.mark.parametrize("below", ["Data", "2026"])
def test_case_probe_does_not_judge_an_empty_folder_by_a_case_sensitive_parent(
    below, answer, same, tmp_path, monkeypatch
):
    """An empty folder keeps its own rule under a folder that minds case.

    On Linux an empty folder can fold case inside one that does not. When
    the folder's rule is unknown, names differing in case match, which can
    only refuse a save.
    """
    import os
    case = tmp_path / "Case"
    folder = case / below
    folder.mkdir(parents=True)
    a, b, c = (str(folder / n) for n in ("B.jser", "b.jser", "C.jser"))

    with monkeypatch.context() as m:
        _folder_minds_case_of(m, folder)
        _folder_minds_case_of(m, case)
        _system_says(m, answer)
        assert _same_both_ways(a, b) == same
        assert not _same_both_ways(a, c)
    assert os.listdir(folder) == []


@pytest.mark.parametrize(
    "answer, same", [(False, False), (None, True), (True, True)],
    ids=["minds-case", "cannot-tell", "folds-case"],
)
def test_case_probe_does_not_judge_an_empty_folder_by_a_case_insensitive_parent(
    answer, same, tmp_path, monkeypatch
):
    """An empty folder that minds case keeps it under a folder that does not.

    On Windows an empty folder can be case-sensitive inside one that is not,
    and then B.jser and b.jser are two files.
    """
    case = tmp_path / "Case"
    folder = case / "Data"
    folder.mkdir(parents=True)
    if not _volume_ignores_case(case):
        pytest.skip("this volume is case-sensitive")
    a, b = str(folder / "B.jser"), str(folder / "b.jser")

    with monkeypatch.context() as m:
        _system_says(m, answer)
        assert _same_both_ways(a, b) == same


def test_system_case_answer_matches_the_folder(tmp_path):
    """Where the system answers for an empty folder, it agrees with a probe file."""
    import os
    import sys
    from PyReconstruct.modules.gui.main.main_window import _askFolderCase

    folder = tmp_path / "Empty"
    folder.mkdir()
    answer = _askFolderCase(str(folder))
    if sys.platform == "darwin":
        assert answer is not None
    if answer is not None:
        assert answer == _volume_ignores_case(folder)
    assert os.listdir(folder) == []


@pytest.mark.parametrize("platform, command, answer", [
    ("linux", ["chattr", "+F"], True),
    ("win32", ["fsutil.exe", "file", "setCaseSensitiveInfo"], False),
], ids=["linux-casefold", "windows-case-sensitive"])
def test_system_reports_a_folder_set_apart_from_its_parent(
    platform, command, answer, tmp_path
):
    """A folder given its own case rule is reported by that rule, not its parent's."""
    import subprocess
    import sys
    from PyReconstruct.modules.gui.main.main_window import (
        _askFolderCase, _samePath,
    )

    if not sys.platform.startswith(platform):
        pytest.skip(f"needs {platform}")
    folder = tmp_path / "Data"
    folder.mkdir()
    argv = command + [str(folder)]
    if platform == "win32":
        argv.append("enable")
    try:
        done = subprocess.run(argv, capture_output=True)
    except OSError as e:
        pytest.skip(f"cannot run {command[0]}: {e}")
    if done.returncode != 0:
        pytest.skip(f"this volume has no per-folder case rule: {done.stderr!r}")

    assert _askFolderCase(str(folder)) is answer
    assert _samePath(str(folder / "B.jser"), str(folder / "b.jser")) is answer


def test_case_probe_follows_a_folder_symlink_in_either_order(tmp_path, monkeypatch):
    """An empty folder reached through a link is judged where it really is."""
    import os

    data = tmp_path / "volume" / "Data"
    data.mkdir(parents=True)
    if not _volume_ignores_case(data):
        pytest.skip("this volume is case-sensitive")
    links = tmp_path / "links"
    links.mkdir()
    alias = links / "Alias"
    try:
        os.symlink(data, alias, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"cannot make a symlink here: {e}")
    inside = str(links) + os.sep

    def reject(p):  # the folder holding the link minds case
        if not p.startswith(inside):
            return False
        return p[len(inside):].split(os.sep)[0] not in os.listdir(links)

    with monkeypatch.context() as m:
        _fake_case_rules(m, reject)
        assert _same_both_ways(str(alias / "B.jser"), str(data / "b.jser"))
        assert not _same_both_ways(str(alias / "B.jser"), str(data / "C.jser"))


def _fake_mount(monkeypatch, mount):
    """Make os.stat and os.lstat put a folder on a volume of its own.

    The folder and everything in it get another st_dev than the folder
    holding it, the way a drive mounted there would, and nothing else
    changes. Names inside keep the case rules of the test volume.
    """
    import os
    import stat
    mount = os.path.normcase(os.path.realpath(mount))
    inside = mount + os.sep
    real_stat, real_lstat = os.stat, os.lstat

    def wrap(real):
        def fake(p, *a, **k):
            st = real(p, *a, **k)
            path = os.fspath(p) if isinstance(p, (str, os.PathLike)) else None
            if not isinstance(path, str):
                return st
            path = os.path.normcase(os.path.normpath(path))
            if path != mount and not path.startswith(inside):
                return st
            fields = list(st)
            fields[stat.ST_DEV] = st.st_dev + 1
            # the rest by name; Python 3.13 refuses a field given twice
            in_fields = os.stat_result.__match_args__
            named = {
                n: getattr(st, n) for n in dir(st)
                if n.startswith("st_") and n not in in_fields
            }
            return os.stat_result(fields, named)
        return fake

    monkeypatch.setattr(os, "stat", wrap(real_stat))
    monkeypatch.setattr(os, "lstat", wrap(real_lstat))


def _folder_minds_case_of(monkeypatch, folder):
    """Make the folder holding `folder` find it only by its exact name."""
    import os
    holder, name = os.path.split(os.path.realpath(folder))
    inside = holder + os.sep

    def reject(p):
        if not p.startswith(inside):
            return False
        first = p[len(inside):].split(os.sep)[0]
        return first != name and first.casefold() == name.casefold()

    _fake_case_rules(monkeypatch, reject)


@pytest.mark.parametrize("below", ["", "2026"], ids=["mount", "folder-in-mount"])
def test_case_probe_does_not_judge_an_empty_mount_by_the_folder_above(
    below, tmp_path, monkeypatch
):
    """An empty mount cannot tell its case, so names differing in case match.

    Looking the mount's name up in the folder above tests that folder's
    volume. Saying the names match can only refuse a save.
    """
    mount = tmp_path / "Data"
    folder = mount / below if below else mount
    folder.mkdir(parents=True)
    a, b, c = (str(folder / n) for n in ("B.jser", "b.jser", "C.jser"))

    with monkeypatch.context() as m:
        _folder_minds_case_of(m, mount)
        _system_says(m, None)
        _fake_mount(m, mount)
        assert _same_both_ways(a, b)
        assert not _same_both_ways(a, c)


def test_save_as_refuses_a_scene_series_in_other_case_on_an_empty_mount(
    main_window, main_window_dialogs, tmp_path, series_jser, monkeypatch
):
    """The other series' .jser is gone and its mount is empty, so its name is still taken."""
    import os

    window = main_window
    _viewer_, _mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    os.remove(other_fp)
    mount = os.path.dirname(other_fp)
    assert os.listdir(mount) == []
    own_fp = window.series.jser_fp
    chosen = os.path.join(mount, "OTHER.jser")

    with monkeypatch.context() as m:
        _folder_minds_case_of(m, mount)
        _system_says(m, None)
        _fake_mount(m, mount)
        main_window_dialogs.file_responses.append(chosen)
        result = window.saveAsToJser()

    assert result == "cancel"
    assert window.series.jser_fp == own_fp
    assert theirs.series_fp == other_fp
    assert os.listdir(mount) == []
    assert any(
        "3D scene" in text for _title, text in main_window_dialogs.message_boxes
    )


@pytest.mark.parametrize(
    "answer, refused", [(True, True), (None, True), (False, False)],
    ids=["folds-case", "cannot-tell", "minds-case"],
)
def test_save_as_judges_an_empty_folder_by_its_own_case_rule(
    answer, refused, main_window, main_window_dialogs, tmp_path, series_jser,
    monkeypatch,
):
    """The other series' .jser is gone, and its folder's rule decides, not the folder above.

    The folder above minds case. If the empty folder folds case, or cannot
    tell, OTHER.jser is the scene series' name and Save As refuses it. If
    the folder minds case too, OTHER.jser is another file and Save As goes
    ahead.
    """
    import os
    window = main_window
    _viewer_, _mine, theirs, other_fp = _scene_with_other_series(
        window, tmp_path, series_jser, monkeypatch
    )
    os.remove(other_fp)
    folder = os.path.dirname(other_fp)
    assert os.listdir(folder) == []
    own_fp = window.series.jser_fp
    chosen = os.path.join(folder, "OTHER.jser")

    with monkeypatch.context() as m:
        _folder_minds_case_of(m, folder)
        _system_says(m, answer)
        main_window_dialogs.file_responses.append(chosen)
        result = window.saveAsToJser()

    assert theirs.series_fp == other_fp
    in_scene = [
        text for _title, text in main_window_dialogs.message_boxes
        if "3D scene" in text
    ]
    if refused:
        assert result == "cancel"
        assert window.series.jser_fp == own_fp
        assert os.listdir(folder) == []
        assert in_scene
    else:
        assert result is None
        assert window.series.jser_fp == chosen
        assert in_scene == []

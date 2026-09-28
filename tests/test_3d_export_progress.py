"""The 3D export shows a bar through its whole run (fork #421 follow-up).

get_3D_meshes shows "Building 3D meshes..." over the section pass. The mesh
writing (export meshes) and measuring (export 3D data) that follow had no bar,
and on a big object that half is the slow one. Both now show a per-object bar
with a time estimate.
"""
import os
import shutil

import pytest
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.progress import NullProgressReporter

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


class Capturing(NullProgressReporter):
    made = []
    finished = []

    def __init__(self, text="", cancel=True, eta=False):
        super().__init__(text, cancel, eta)
        Capturing.made.append((text, eta))

    def finish(self):
        Capturing.finished.append(self.text)
        super().finish()


def _open(tmp_path):
    src = os.path.join(FIXTURE_DIR, "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(src, fp)
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    s = Series.openJser(fp)
    Capturing.made = []
    Capturing.finished = []
    s.setProgressReporter(Capturing)
    return s


def test_export_meshes_shows_a_bar_for_the_write_phase(tmp_path, monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    s = _open(tmp_path)
    try:
        monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
        name = sorted(s.data["objects"].keys())[0]
        s.setAttr(name, "3D_mode", "surface")
        out = tmp_path / "out"
        out.mkdir()
        ev.export3DObjects(s, [name], str(out), "stl")

        assert (out / f"{name}.stl").exists()
        assert Capturing.made == [
            ("Building 3D meshes...", True),
            ("Writing 3D meshes...", True),
        ]
        assert "Writing 3D meshes..." in Capturing.finished
    finally:
        s.close()


def test_export_data_shows_a_bar_for_the_measure_phase(tmp_path, monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    s = _open(tmp_path)
    try:
        monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
        name = sorted(s.data["objects"].keys())[0]
        s.setAttr(name, "3D_mode", "surface")
        out = tmp_path / "mesh_data.csv"
        ev.export3DData(s, [name], str(out))

        assert out.exists()
        assert Capturing.made == [
            ("Building 3D meshes...", True),
            ("Measuring 3D meshes...", True),
        ]
        assert "Measuring 3D meshes..." in Capturing.finished
    finally:
        s.close()


def test_a_factory_without_the_eta_flag_still_works(tmp_path, monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    class OldStyle(NullProgressReporter):
        made = []

        def __init__(self, text="", cancel=True):
            super().__init__(text, cancel)
            OldStyle.made.append(text)

    s = _open(tmp_path)
    try:
        s.setProgressReporter(OldStyle)
        monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
        name = sorted(s.data["objects"].keys())[0]
        s.setAttr(name, "3D_mode", "surface")
        ev.export3DData(s, [name], str(tmp_path / "d.csv"))
        assert "Measuring 3D meshes..." in OldStyle.made
    finally:
        s.close()


def test_a_failed_mesh_write_still_closes_the_bar(tmp_path, monkeypatch):
    """The bar has no Cancel button and closes only at 100%. A write that
    raises must not leave it parked below that, blocking the window."""
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    from PyReconstruct.modules.backend.volume.objects_3D import Surface

    s = _open(tmp_path)
    try:
        monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
        name = sorted(s.data["objects"].keys())[0]
        s.setAttr(name, "3D_mode", "surface")

        def boom(self, *a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(Surface, "exportTrimesh", boom)
        with pytest.raises(OSError):
            ev.export3DObjects(s, [name], str(tmp_path), "stl")

        assert "Writing 3D meshes..." in Capturing.finished, (
            "the write bar was left open after the failure"
        )
    finally:
        s.close()

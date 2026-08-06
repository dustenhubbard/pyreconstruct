"""Regression tests for the images-not-found auto-recovery in openSeries.

Bug: when a series was opened whose ``src_dir`` no longer resolved, openSeries
probed for the image file next to the jser and, on a hit, called
``changeSrcDir(src_path)`` with that **file** path. ``changeSrcDir`` documents
its argument as "the new image directory" and assigns it straight to
``series.src_dir``, which ``Section.src_fp`` joins with ``section.src``. Passing
a file therefore produced a doubled path (``.../shapes_0.tif/shapes_0.tif``),
so the images stayed missing - yet ``changeSrcDir`` had already called
``seriesModified(True)``. The user was told nothing, the images never appeared,
and the freshly opened series looked dirty.

The shipped checker fixture reproduces the trigger exactly: ``shapes1.jser``
records ``src_dir = ""`` and its TIFFs sit in the jser's own directory.

Fix: ``findImagesBesideJser`` probes for the file but passes its DIRECTORY, and
reports whether the images actually loaded so openSeries can fall through to the
existing interactive prompt instead of failing silently.

The GUI method is driven against duck-typed stubs (the pattern used by
test_set_series_mag / test_missing_return_guards), so no real MainWindow or Qt
event loop is required.
"""
import os
import types

import pytest

from PyReconstruct.modules.gui.main import main_window as mw


# --------------------------------------------------------------------------
# Stubs: a src_fp that joins src_dir with src, exactly as Section.src_fp does.
# --------------------------------------------------------------------------
class _SeriesStub:
    def __init__(self, jser_fp, src_dir=""):
        self.jser_fp = jser_fp
        self.src_dir = src_dir
        self.modified = False


class _SectionLayerStub:
    """image_found is recomputed from the series' current src_dir on reload."""

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.is_zarr_file = False
        self.is_scaled = True
        self.image_found = False

    def loadImage(self):
        self.image_found = os.path.isfile(
            os.path.join(self.series.src_dir, self.section.src)
        )


class _FieldStub:
    def __init__(self, series, section):
        self.section = section
        self.section_layer = _SectionLayerStub(series, section)
        self.reloads = 0

    def reloadImage(self):
        self.reloads += 1
        self.section_layer.loadImage()


class _MainWindowStub:
    def __init__(self, jser_fp, src_dir=""):
        self.series = _SeriesStub(jser_fp, src_dir)
        self.section = types.SimpleNamespace(src="shapes_0.tif")
        self.field = _FieldStub(self.series, self.section)
        self.modified_calls = []

    def seriesModified(self, modified=True):
        self.modified_calls.append(modified)
        self.series.modified = modified

    def changeSrcDir(self, *args, **kwargs):
        """Delegate to the REAL method - it is what assigns series.src_dir."""
        return mw.MainWindow.changeSrcDir(self, *args, **kwargs)


def _series_with_images(tmp_path):
    """A jser and its image sitting in the same directory."""
    jser_fp = tmp_path / "shapes1.jser"
    jser_fp.write_text("{}")
    (tmp_path / "shapes_0.tif").write_bytes(b"fake tif bytes")
    return _MainWindowStub(str(jser_fp))


# --------------------------------------------------------------------------
# The core defect: src_dir must end up a DIRECTORY, and src_fp must resolve.
# --------------------------------------------------------------------------
def test_recovery_sets_src_dir_to_a_directory_not_the_image_file(tmp_path):
    stub = _series_with_images(tmp_path)

    recovered = mw.MainWindow.findImagesBesideJser(stub)

    assert recovered is True, "the image is beside the jser and must be found"
    assert os.path.isdir(stub.series.src_dir), (
        f"src_dir must be a directory, got {stub.series.src_dir!r}"
    )
    assert stub.series.src_dir == str(tmp_path)


def test_recovery_does_not_produce_a_doubled_src_fp(tmp_path):
    """The reported symptom: .../shapes_0.tif/shapes_0.tif."""
    stub = _series_with_images(tmp_path)

    mw.MainWindow.findImagesBesideJser(stub)

    src_fp = os.path.join(stub.series.src_dir, stub.section.src)
    assert src_fp.count("shapes_0.tif") == 1, f"doubled image path: {src_fp}"
    assert os.path.isfile(src_fp), f"recovered src_fp does not exist: {src_fp}"


def test_recovery_actually_loads_the_image(tmp_path):
    """The whole point of the recovery: image_found must flip to True."""
    stub = _series_with_images(tmp_path)

    mw.MainWindow.findImagesBesideJser(stub)

    assert stub.field.section_layer.image_found is True, (
        "auto-recovery reported success but the image never loaded"
    )


# --------------------------------------------------------------------------
# The silent-failure half: a recovery that does not work must not be reported
# as success, so openSeries can still prompt the user.
# --------------------------------------------------------------------------
def test_no_candidate_beside_jser_reports_failure_without_touching_series(tmp_path):
    jser_fp = tmp_path / "shapes1.jser"
    jser_fp.write_text("{}")  # no shapes_0.tif beside it
    stub = _MainWindowStub(str(jser_fp), src_dir="/nonexistent")

    assert mw.MainWindow.findImagesBesideJser(stub) is False
    assert stub.series.src_dir == "/nonexistent", "src_dir must be left alone"
    assert stub.modified_calls == [], "a no-op must not mark the series modified"


def test_unloadable_candidate_reports_failure(tmp_path, monkeypatch):
    """A file of the right name that will not load is not a success."""
    stub = _series_with_images(tmp_path)
    monkeypatch.setattr(
        _SectionLayerStub, "loadImage", lambda self: None  # stays image_found=False
    )

    assert mw.MainWindow.findImagesBesideJser(stub) is False, (
        "recovery must report failure when the image does not load, so the "
        "caller can prompt instead of silently leaving the user with no images"
    )


# --------------------------------------------------------------------------
# openSeries wiring: failure must reach the interactive prompt.
# --------------------------------------------------------------------------
def test_openSeries_prompts_when_auto_recovery_fails(monkeypatch):
    """The user must be asked to locate images rather than told nothing.

    The image block moved out of ``openSeries`` into
    ``_ensureImagesAvailable`` when the 200-line method was decomposed, so
    read the step and check ``openSeries`` still calls it. Both halves are
    asserted: neither the step existing unwired nor ``openSeries`` calling a
    step that lost the recovery is enough on its own.

    The negative assertion deliberately reads the whole ``MainWindow`` class
    rather than one method. A negative assertion's power is exactly the size
    of the text it reads: scoped to ``_ensureImagesAvailable`` it would let
    the buggy call reappear anywhere else in the open sequence - including
    back in ``openSeries`` itself, where it used to live - without failing.
    Reading the class is also refactor-proof in a way that reading one
    method's source is not.
    """
    import inspect

    assert "self._ensureImagesAvailable()" in inspect.getsource(
        mw.MainWindow.openSeries
    ), "openSeries must still run the images step"

    src = inspect.getsource(mw.MainWindow._ensureImagesAvailable)
    assert "findImagesBesideJser()" in src, (
        "openSeries should route missing images through the recovery helper"
    )
    assert "self.changeSrcDir(notify=True)" in src, (
        "a failed auto-recovery must fall through to the interactive prompt"
    )
    # and the old file-path call must be gone - from anywhere in the class,
    # not merely from the step the image block was decomposed into
    assert "self.changeSrcDir(src_path)" not in inspect.getsource(
        mw.MainWindow
    ), "MainWindow must not hand changeSrcDir a file path"


# --------------------------------------------------------------------------
# End-to-end against the shipped fixture: Section.src_fp is the real thing.
# --------------------------------------------------------------------------
FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


def test_real_section_src_fp_resolves_after_recovery():
    """Uses the real Section.src_fp, which is what the buggy value fed."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series

    series = Series.openJser(FIXTURE)
    try:
        section = series.loadSection(list(series.sections.keys())[0])
        jser_dir = os.path.dirname(os.path.abspath(FIXTURE))
        candidate = os.path.join(jser_dir, os.path.basename(section.src))
        assert os.path.isfile(candidate), "fixture should ship images by the jser"

        # what the bug did: src_dir = the file path
        series.src_dir = candidate
        assert not os.path.isfile(section.src_fp), (
            "sanity: a file-valued src_dir must yield a broken src_fp"
        )
        assert section.src_fp.count(os.path.basename(section.src)) == 2

        # what the fix does: src_dir = the directory
        series.src_dir = jser_dir
        assert os.path.isfile(section.src_fp), (
            f"a directory-valued src_dir must resolve: {section.src_fp}"
        )
    finally:
        series.close()

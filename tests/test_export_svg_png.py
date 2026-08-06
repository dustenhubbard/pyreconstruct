"""Regression tests for SVG/PNG section export and the two packages it needs.

The bug: ``PyReconstruct/modules/backend/exports/svg_conversion.py`` imports
``svgwrite`` (for ``export_svg``) and ``cairosvg`` (for ``export_png``), and
neither package was declared in ``pyproject.toml``, ``requirements.txt`` or
``uv.lock``. ``git log -S svgwrite`` shows they arrived with the feature commits
that wrote the module and were never added to a dependency file by any of them.

What that cost a user was **not** a traceback. ``File > Export > SVG`` and
``File > Export > PNG`` (``main_window.py``) each open with a
``modules_available(...)`` guard that predates this branch -- both lines came in
with ``91c33027``, the same upstream commit that added the export -- and there
is no other caller of ``exportAsSVG``/``exportAsPNG`` in the application. So the
guard caught the ``ModuleNotFoundError`` every time and put up a dialog offering
to ``pip install`` the two packages over the network, or no-oped on decline.

That is still a genuine packaging defect: a shipped feature nagged every user to
self-install two packages the distribution should have carried, and the export
did not work until they accepted. It is a smaller and differently-shaped defect
than "the export crashes", which is what an earlier draft of this file said.

Nothing caught it because nothing tested it. No test in the suite touched
``export_svg``, ``export_png``, ``exportAsSVG`` or ``exportAsPNG``, so the only
signal available was a user trying to export.

Declaring ``cairosvg`` had a second-order consequence that this branch also
fixes, because the guard is what made it visible: ``modules_available`` caught
``ModuleNotFoundError`` only, and ``import cairosvg`` raises ``OSError`` when
native Cairo is absent. Once every user has the wheel, that ``OSError`` escapes
the guard as a crash on any machine without Cairo. The guard is widened in
``mod_imports.py`` on this branch and covered by
``tests/test_modules_available_native_library.py``.

The four tests below are layered so that a regression is reported at the layer
it actually happened at:

1. ``test_export_packages_are_declared`` reads the dependency files. It fails if
   someone drops the declaration, and it fails identically on every platform,
   including one where the native half of cairo is unavailable.
2. ``test_export_packages_are_importable`` proves the declaration produced an
   installed package, which is the part a file-contents check cannot see.
3. ``test_export_as_svg_writes_a_real_svg`` runs the real export and checks the
   output is an SVG carrying this section's image and traces -- not merely that
   the call did not raise.
4. ``test_export_as_png_writes_a_real_png`` does the same for PNG, and is the
   one test here that can skip. See its docstring: ``cairosvg`` reaches Cairo
   through a runtime ``dlopen``, so a machine can have the wheel and still not
   be able to render. That is a real, separate deployment requirement rather
   than a detail, so the skip names it instead of hiding it, and CI installs
   ``libcairo2`` so the assertion runs there.

The fixture is the shipped checker series ``shapes1.jser`` plus its five TIFFs.
It is used rather than a synthetic stub because ``export_svg`` reads the section
image off disk (``getImgDims`` -> ``cv2.imread``, then ``PIL.Image.open`` for the
base64 embed) and walks real ``Trace`` objects through ``asPixels``; a stub
section would exercise none of that. ``shapes1.jser`` records ``src_dir = ""``
with its images beside it, so the copy sets ``src_dir`` to the temporary
directory the way ``openSeries``'s images-beside-the-jser recovery does.
"""

import shutil
import struct
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_FILES = REPO_ROOT / "dev" / "assets" / "checker" / "files"
FIXTURE_JSER = CHECKER_FILES / "shapes1.jser"

SVG_NS = "http://www.w3.org/2000/svg"

# The two packages, and the file that imports each one.
EXPORT_PACKAGES = ["svgwrite", "cairosvg"]


@pytest.fixture
def exportable_series(tmp_path):
    """A real Series whose section images resolve, opened from a writable copy.

    Both the jser and the TIFFs are copied: the export reads the images, and the
    series is pointed at the copy rather than at the shipped asset so a run
    cannot dirty the checked-in fixture.
    """
    if not FIXTURE_JSER.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE_JSER}")

    destination = tmp_path / "shapes1.jser"
    shutil.copy(FIXTURE_JSER, destination)
    for tif in sorted(CHECKER_FILES.glob("shapes_*.tif")):
        shutil.copy(tif, tmp_path / tif.name)

    from PyReconstruct.modules.datatypes import Series

    series = Series.openJser(str(destination))
    # shapes1.jser records src_dir = "" and keeps its images next to itself, so
    # this is the same repoint findImagesBesideJser performs on open.
    series.src_dir = str(tmp_path)
    yield series
    series.close()


def _cairo_native_error():
    """Return the OSError cairocffi raises when it cannot find libcairo, else None.

    ``import cairosvg`` executes ``cairocffi``'s ``dlopen`` at import time, so
    this doubles as the native-library probe for the render test.

    A *missing package* deliberately reports ``None`` rather than an error: that
    is the regression this file exists to catch, and it must reach the export
    call and fail there with the pointed message, not be skipped away as if it
    were the system-library case. The two failures look alike from a distance
    and have completely different fixes.
    """
    try:
        import cairosvg  # noqa: F401
    except ModuleNotFoundError:
        return None  # the declaration regression -- do not skip, let it fail
    except OSError as exc:  # cairocffi: 'no library called "cairo-2" was found'
        return exc
    return None


# --------------------------------------------------------------------------
# 1. The declaration. Platform-independent, and the layer the bug was at.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("package", EXPORT_PACKAGES)
def test_export_packages_are_declared(package):
    """Both packages must be declared where an install will actually read them.

    ``pyproject.toml`` is the source of truth for the uv workflow (and for
    ``pip install .``). ``requirements.txt`` is checked too because it is not
    dead: ``dev/environment_dev.yaml`` includes it and the four ``launch/*``
    self-update scripts run ``pip install -r requirements.txt`` on startup, so a
    package missing there is a broken install on somebody's next launch even
    once ``pyproject.toml`` is right.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    declared = pyproject["project"]["dependencies"]
    names = [d.split("==")[0].split(">")[0].split("<")[0].strip() for d in declared]
    assert package in names, (
        f"{package} is imported by modules/backend/exports/svg_conversion.py but "
        f"is not in [project.dependencies]; without it SVG/PNG export cannot "
        f"run and the main_window guard nags the user to pip-install it"
    )

    requirements = (REPO_ROOT / "requirements.txt").read_text().splitlines()
    req_names = [
        line.split("==")[0].strip()
        for line in requirements
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert package in req_names, (
        f"{package} is in pyproject.toml but not requirements.txt, which the "
        f"conda env and the launch/ self-update scripts install from"
    )


@pytest.mark.parametrize("package", EXPORT_PACKAGES)
def test_export_packages_are_importable(package):
    """The declaration has to have produced an installed distribution.

    ``importlib.util.find_spec`` rather than ``import``: for ``cairosvg`` the
    import itself can fail on the native library even when the Python package is
    correctly installed, and that is a different failure with a different fix.
    This test is about the packaging half only, and holds on a machine with no
    Cairo at all.
    """
    import importlib.util

    assert importlib.util.find_spec(package) is not None, (
        f"{package} is declared but not installed in this environment; "
        f"re-run `uv sync --frozen --no-default-groups --extra test`"
    )


# --------------------------------------------------------------------------
# 2. The export itself, against real section data.
# --------------------------------------------------------------------------
def test_export_as_svg_writes_a_real_svg(exportable_series, tmp_path):
    """``Section.exportAsSVG`` produces an SVG with this section's image and traces.

    Asserting on the content, not on the absence of an exception: "did not
    crash" would have passed against a zero-byte file, and the point of the test
    is that the export path works end to end.
    """
    section = exportable_series.loadSection(min(exportable_series.sections.keys()))
    height, width = section.img_dims
    expected_names = set(section.contours.keys())
    assert expected_names, "fixture section has no contours; test proves nothing"

    out = tmp_path / "section.svg"
    try:
        returned = section.exportAsSVG(str(out))
    except ModuleNotFoundError as exc:  # the original bug, named explicitly
        pytest.fail(
            f"SVG export raised ModuleNotFoundError ({exc.name}): the export's "
            f"dependencies are undeclared or uninstalled again"
        )

    assert Path(returned) == out
    assert out.is_file() and out.stat().st_size > 0

    root = ET.parse(out).getroot()
    assert root.tag == f"{{{SVG_NS}}}svg"
    # svgwrite writes the size it was handed, which is the image's own pixel size.
    assert root.get("width") == str(width)
    assert root.get("height") == str(height)

    # The image layer embeds the section TIFF as a base64 PNG data URI. Its
    # absence would mean an SVG of bare outlines on nothing.
    images = root.iter(f"{{{SVG_NS}}}image")
    hrefs = [
        img.get("{http://www.w3.org/1999/xlink}href") or img.get("href")
        for img in images
    ]
    assert len(hrefs) == 1, "expected exactly one embedded section image"
    assert hrefs[0].startswith("data:image/png;base64,")
    assert len(hrefs[0]) > 1000, "embedded image is too small to be the section"

    # Every visible trace becomes a path whose id is the trace name, plus the
    # scale bar the exporter draws itself.
    path_ids = {p.get("id") for p in root.iter(f"{{{SVG_NS}}}path")}
    assert "scale_bar" in path_ids
    assert expected_names <= path_ids, (
        f"traces missing from the SVG: {sorted(expected_names - path_ids)}"
    )

    # A path with no geometry would still satisfy the id check above.
    for path in root.iter(f"{{{SVG_NS}}}path"):
        assert path.get("d", "").startswith("M "), f"empty path for {path.get('id')}"


def test_export_as_png_writes_a_real_png(exportable_series, tmp_path, monkeypatch):
    """``Section.exportAsPNG`` rasterizes the SVG to a PNG at the requested scale.

    This is the one test here that can skip, and the reason is a genuine
    deployment constraint rather than an environment quirk worth papering over:
    ``cairosvg`` does not bundle Cairo. It imports ``cairocffi``, which
    ``dlopen``s the *native* library at import time, so `pip install cairosvg`
    succeeds on a machine that then raises
    ``OSError: no library called "cairo-2" was found`` on first use. Declaring
    the package -- which is what this branch fixes -- is necessary but not
    sufficient for PNG export; the machine also needs ``libcairo2``
    (Debian/Ubuntu) or ``brew install cairo`` (macOS), and on macOS Homebrew's
    ``/opt/homebrew/lib`` is not searched by ``ctypes.util.find_library``, so it
    additionally needs ``DYLD_FALLBACK_LIBRARY_PATH`` to point there. SVG export
    needs none of this and is asserted unconditionally above.

    CI installs ``libcairo2``, so this does not skip on the gate.
    """
    native_error = _cairo_native_error()
    if native_error is not None:
        pytest.skip(
            "cairosvg is installed but native Cairo is not loadable here, so PNG "
            "export cannot run: install libcairo2 (Debian/Ubuntu) or `brew "
            "install cairo` and set DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "
            f"(macOS). Underlying error: {native_error}"
        )

    section = exportable_series.loadSection(min(exportable_series.sections.keys()))
    height, width = section.img_dims

    # Record where the intermediate SVG actually lands so the cleanup check
    # below has a real path to test. `export_png` calls `mkstemp(suffix=".svg")`
    # with no `dir=`, so it goes to the *system* temp directory -- globbing the
    # PNG's own parent (which is tmp_path) would look in a directory the file
    # was never written to and pass whether or not the cleanup ran.
    from PyReconstruct.modules.backend.exports import svg_conversion

    tmp_svgs = []
    real_mkstemp = svg_conversion.mkstemp

    def recording_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        tmp_svgs.append(path)
        return fd, path

    monkeypatch.setattr(svg_conversion, "mkstemp", recording_mkstemp)

    scale = 0.25  # small on purpose: a full-size raster is slow and proves no more
    out = tmp_path / "section.png"
    try:
        returned = section.exportAsPNG(str(out), scale)
    except ModuleNotFoundError as exc:  # the original bug, on the PNG branch
        pytest.fail(
            f"PNG export raised ModuleNotFoundError ({exc.name}): the export's "
            f"dependencies are undeclared or uninstalled again"
        )

    assert Path(returned) == out
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "output is not a PNG"

    # IHDR is the first chunk and carries the raster's real dimensions, so this
    # checks the section was rendered at the requested scale rather than that
    # some PNG was written.
    assert data[12:16] == b"IHDR"
    png_width, png_height = struct.unpack(">II", data[16:24])
    assert png_width == round(width * scale)
    assert png_height == round(height * scale)

    # A blank raster of the right size would pass everything above; the section
    # image and traces make it substantially larger than an empty one.
    assert len(data) > 2000, "PNG is too small to contain the rendered section"

    # export_png writes the intermediate SVG to a mkstemp path and unlinks it.
    # Asserted against the path mkstemp really returned: delete the `unlink`
    # from export_png and this fails, which is the only reason to keep it.
    assert len(tmp_svgs) == 1, "export_png did not take the mkstemp path once"
    assert not Path(tmp_svgs[0]).exists(), (
        f"export_png left its intermediate SVG behind at {tmp_svgs[0]}"
    )

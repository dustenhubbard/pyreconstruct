"""Regression tests for SVG/PNG section export and the packages it needs.

The bug: ``PyReconstruct/modules/backend/exports/svg_conversion.py`` imports
``svgwrite`` (for ``export_svg``) and ``cairosvg`` (for ``export_png``), and
neither package was declared in ``pyproject.toml``, ``requirements.txt`` or
``uv.lock``. ``git log -S svgwrite`` shows they arrived with the feature commits
that wrote the module and were never added to a dependency file by any of them.

``pillow`` was the third and is covered here too, added after the other two.
``export_svg`` does ``from PIL import Image`` to re-encode the section image
into the SVG's base64 data URI, and it was undeclared for the same reason. It
never failed for anybody, because five locked packages pull pillow in
transitively -- ``cairosvg`` and ``scikit-image`` directly, ``imageio`` via
``scikit-image``, ``matplotlib`` via ``vtk``, ``neuroglancer`` via the dev-only
``funlib-show-neuroglancer`` -- but a transitive edge is somebody else's
promise, and it takes one dependency bump to withdraw it. It is also the *worse*
of the three gaps if it ever opens: the guard described below covers ``svgwrite``
and ``cairosvg`` and does not probe ``PIL`` at all, so a missing pillow is an
uncaught ``ModuleNotFoundError`` rather than a dialog.
``test_svg_export_is_not_guarded_against_a_missing_pillow`` pins that
difference.

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

The tests below are layered so that a regression is reported at the layer it
actually happened at:

1. ``test_export_packages_are_declared`` reads the dependency files. It fails if
   someone drops the declaration, and it fails identically on every platform,
   including one where the native half of cairo is unavailable.
2. ``test_export_packages_are_importable`` proves the declaration produced an
   installed package, which is the part a file-contents check cannot see.
3. ``test_export_as_svg_writes_a_real_svg`` runs the real export and checks the
   output is an SVG carrying this section's image and traces -- not merely that
   the call did not raise.
4. ``test_export_svg_embeds_a_png_pillow_actually_produced`` decodes that
   embedded image and reads its PNG header, so the pillow leg of the export is
   asserted on its output rather than on the package being importable.
5. ``test_svg_export_is_not_guarded_against_a_missing_pillow`` injects a missing
   pillow and shows the guard passes and the export raises, which is the reason
   the declaration is worth having rather than relying on the transitive edges.
6. ``test_export_as_png_writes_a_real_png`` does what (3) does for PNG, and is
   the one test here that can skip. See its docstring: ``cairosvg`` reaches
   Cairo through a runtime ``dlopen``, so a machine can have the wheel and still
   not be able to render. That is a real, separate deployment requirement rather
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

import ast
import base64
import shutil
import struct
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_FILES = REPO_ROOT / "dev" / "assets" / "checker" / "files"
FIXTURE_JSER = CHECKER_FILES / "shapes1.jser"
MAIN_WINDOW = REPO_ROOT / "PyReconstruct" / "modules" / "gui" / "main" / "main_window.py"

SVG_NS = "http://www.w3.org/2000/svg"

# Every package ``svg_conversion.py`` imports directly, as
# {distribution name: import name}. The two differ for pillow, which is why
# this is a mapping: the declaration tests read distribution names out of the
# dependency files, the importability test needs the import name.
#
# ``zarr`` and ``cv2`` are imported by the same module and are deliberately
# absent: both were already declared (as ``zarr`` and
# ``opencv-python-headless``) before any of this, so they are not part of the
# gap these tests exist to hold shut.
EXPORT_PACKAGES = {
    "svgwrite": "svgwrite",
    "cairosvg": "cairosvg",
    "pillow": "PIL",
}


def menu_guard_modules(export_method: str) -> list:
    """The module list the REAL menu guard in front of ``export_method`` probes.

    Read out of ``main_window.py``'s own source rather than hand-copied into
    this file, and that distinction is the whole point of this helper.
    ``test_svg_export_is_not_guarded_against_a_missing_pillow`` claims in its
    docstring that widening the guard to probe ``PIL`` would fail it. That
    claim was false for as long as the test wrote ``modules_available(
    "svgwrite", ...)`` as a literal: the literal is not the guard, so widening
    both real call sites in ``main_window.py`` left the whole suite green and
    the sabotage row was decorative. Deriving the argument list from the real
    call site is what makes the claim true.

    Monkeypatching ``modules_available`` and running the export would have been
    the more direct mechanism, and it does not work here: ``Section.exportAsSVG``
    is ``return export_svg(self, svg_fp)`` and consults no guard at all. The
    guard is purely a GUI-menu-level check that an object-level export call
    bypasses entirely -- which is precisely why the export can still raise an
    uncaught ``ModuleNotFoundError``, and why the guard has to be located by
    source rather than observed by running anything. Driving the real
    ``main_window`` method instead would drag in a live ``MainWindow``, a
    ``saveToJser`` and two modal file dialogs to assert one argument list.

    The guard is found by its RELATIONSHIP to the export -- the function that
    calls ``export_method`` -- not by the name ``exportSectionSVG``, so renaming
    the menu handler does not quietly turn this back into a test of nothing.
    Reading the source with ``ast`` rather than importing ``main_window`` keeps
    Qt out of it; the ``modules_available`` name is matched unqualified because
    that is how ``main_imports`` re-exports it.
    """
    tree = ast.parse(MAIN_WINDOW.read_text())

    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    callers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == export_method
    ]
    assert len(callers) == 1, (
        f"expected exactly one call to {export_method} in {MAIN_WINDOW.name}, "
        f"found {len(callers)} at lines {[c.lineno for c in callers]}; the "
        f"guard this test reads is the one in front of THE caller, so a second "
        f"one means there is a second guard (or an unguarded path) to account for"
    )

    enclosing = parents.get(callers[0])
    while enclosing is not None and not isinstance(
            enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
        enclosing = parents.get(enclosing)
    assert enclosing is not None, (
        f"the call to {export_method} at {MAIN_WINDOW.name}:{callers[0].lineno} "
        f"is not inside a function, so it has no guard to read"
    )

    guards = [
        node for node in ast.walk(enclosing)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "modules_available"
    ]
    assert len(guards) == 1, (
        f"expected exactly one modules_available guard in "
        f"{MAIN_WINDOW.name}:{enclosing.name} (which calls {export_method}), "
        f"found {len(guards)} at lines {[g.lineno for g in guards]}"
    )

    assert guards[0].args, (
        f"the guard at {MAIN_WINDOW.name}:{guards[0].lineno} passes its modules "
        f"by keyword; this helper reads the first positional argument"
    )
    try:
        modules = ast.literal_eval(guards[0].args[0])
    except ValueError:  # pragma: no cover - only if the guard stops being a literal
        pytest.fail(
            f"the guard at {MAIN_WINDOW.name}:{guards[0].lineno} no longer passes "
            f"a literal module list, so this test can no longer read what it "
            f"probes and must be rewritten rather than left silently toothless"
        )

    return [modules] if isinstance(modules, str) else list(modules)


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
@pytest.mark.parametrize("package", sorted(EXPORT_PACKAGES))
def test_export_packages_are_declared(package):
    """Each package must be declared where an install will actually read them.

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
        f"is not in [project.dependencies]; without it SVG/PNG export cannot run "
        f"-- and only svgwrite and cairosvg have a modules_available guard in "
        f"front of them, so for pillow the failure is an uncaught "
        f"ModuleNotFoundError rather than the guard's pip-install offer"
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


@pytest.mark.parametrize(
    "package,import_name", sorted(EXPORT_PACKAGES.items())
)
def test_export_packages_are_importable(package, import_name):
    """The declaration has to have produced an installed distribution.

    ``importlib.util.find_spec`` rather than ``import``: for ``cairosvg`` the
    import itself can fail on the native library even when the Python package is
    correctly installed, and that is a different failure with a different fix.
    This test is about the packaging half only, and holds on a machine with no
    Cairo at all.

    The distribution name and the import name are not the same thing for every
    package -- ``pillow`` imports as ``PIL`` -- so the two are carried
    separately rather than assumed equal.
    """
    import importlib.util

    assert importlib.util.find_spec(import_name) is not None, (
        f"{package} is declared but not installed in this environment "
        f"(import name {import_name!r}); "
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


def test_export_svg_embeds_a_png_pillow_actually_produced(
        exportable_series, tmp_path):
    """The embedded image is a real PNG of the section, i.e. pillow did the work.

    ``export_svg`` reads the section image with ``PIL.Image.open`` (or
    ``Image.fromarray`` for a zarr source) and re-encodes it with
    ``image.save(buffered, format="PNG")`` before base64-ing it into the SVG.
    The fixture's source image is a **TIFF**, so a PNG in the output can only
    have come from that round trip -- there is no PNG on disk to copy.

    The test above asserts the data URI's prefix and length, which a truncated
    or garbage payload would also satisfy. This one decodes it and reads the
    PNG header by hand (``struct``, not pillow, so the check does not lean on
    the library it is checking) to assert the raster is the section's own size.
    That is the pillow leg of the export run end to end, rather than
    ``find_spec("PIL")`` succeeding.
    """
    section = exportable_series.loadSection(min(exportable_series.sections.keys()))
    height, width = section.img_dims

    out = tmp_path / "section.svg"
    section.exportAsSVG(str(out))

    root = ET.parse(out).getroot()
    hrefs = [
        img.get("{http://www.w3.org/1999/xlink}href") or img.get("href")
        for img in root.iter(f"{{{SVG_NS}}}image")
    ]
    assert len(hrefs) == 1
    prefix = "data:image/png;base64,"
    assert hrefs[0].startswith(prefix)

    payload = base64.b64decode(hrefs[0][len(prefix):], validate=True)
    assert payload[:8] == b"\x89PNG\r\n\x1a\n", (
        "the embedded data URI says image/png but the bytes are not a PNG"
    )
    assert payload[12:16] == b"IHDR"
    embedded_width, embedded_height = struct.unpack(">II", payload[16:24])
    assert (embedded_width, embedded_height) == (width, height), (
        f"embedded image is {embedded_width}x{embedded_height}, but the section "
        f"image is {width}x{height}"
    )

    # The SVG canvas is sized from the same image, so the two must agree; a
    # mismatch means the embed and the geometry came from different places.
    assert root.get("width") == str(embedded_width)
    assert root.get("height") == str(embedded_height)


def test_svg_export_is_not_guarded_against_a_missing_pillow(
        exportable_series, tmp_path, monkeypatch):
    """Without the declaration, a missing pillow is a crash, not a prompt.

    This is why pillow is declared rather than left to arrive transitively, and
    it is the one way its gap differs from ``svgwrite``'s. ``exportSectionSVG``
    (``main_window.py``) opens with ``modules_available("svgwrite")`` and
    ``exportSectionPNG`` with ``modules_available(["svgwrite", "cairosvg"])`` --
    neither probes ``PIL``. So an environment that resolved without pillow gets
    a guard that says yes and a ``ModuleNotFoundError`` out of ``export_svg``
    immediately afterwards, which reaches ``customExcepthook`` as a crash
    report. ``svgwrite`` and ``cairosvg`` at their worst produced a handled
    dialog offering the pip install.

    The absence is injected through ``sys.meta_path`` rather than by
    uninstalling anything, so this runs on a correctly-installed machine and on
    CI. It asserts the *current* shape of the code -- widening either guard to
    probe ``PIL`` too would be a different fix, and would fail this test, which
    is the intended signal rather than a nuisance.

    That last sentence used to be false. The test wrote the guard's argument
    list out by hand as ``modules_available("svgwrite", notify=False)``, so it
    was measuring a literal in this file and not the guard: widening BOTH real
    call sites in ``main_window.py`` to ``["svgwrite", "PIL"]`` and
    ``["svgwrite", "cairosvg", "PIL"]`` left the entire suite green (6240
    passed, 3 skipped, 6 xfailed -- identical to an unwidened run). The module
    lists below now come from ``menu_guard_modules``, which reads them off the
    real call sites, so both guards are genuinely under this assertion.
    ``notify`` is still passed ``False`` here and only here: the real guards
    pass ``True``, and the point of the probe is what the guard *concludes*,
    which must not depend on a modal dialog nobody is present to answer.
    """
    from PyReconstruct.modules.backend.imports.mod_imports import modules_available

    # Both menu guards, read from main_window.py rather than restated here.
    svg_guard = menu_guard_modules("exportAsSVG")
    png_guard = menu_guard_modules("exportAsPNG")

    section = exportable_series.loadSection(min(exportable_series.sections.keys()))

    class _Loader:
        @staticmethod
        def create_module(spec):
            raise ModuleNotFoundError("No module named 'PIL'", name="PIL")

        @staticmethod
        def exec_module(module):  # pragma: no cover - create_module raises first
            raise ModuleNotFoundError("No module named 'PIL'", name="PIL")

    class _Finder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if fullname != "PIL" and not fullname.startswith("PIL."):
                return None
            from importlib.machinery import ModuleSpec

            return ModuleSpec(fullname, _Loader())

    # An earlier test in this file has already imported pillow, so the cached
    # entries have to go or the finder is never consulted. monkeypatch restores
    # every one of them at teardown.
    for cached in [name for name in sys.modules if name.split(".")[0] == "PIL"]:
        monkeypatch.delitem(sys.modules, cached)
    monkeypatch.setattr(sys, "meta_path", [_Finder()] + list(sys.meta_path))

    # Neither guard names pillow. Asserted on the real argument lists, and
    # separately from the probe below, because this is the claim the file's
    # docstring makes in prose and it deserves to fail by name rather than as
    # "the probe returned False".
    for menu, guard in (("SVG", svg_guard), ("PNG", png_guard)):
        assert not ({"PIL", "pillow"} & set(guard)), (
            f"the File > Export > {menu} guard now probes pillow ({guard}), so a "
            f"missing pillow is a dialog rather than the uncaught "
            f"ModuleNotFoundError this test pins. That is a legitimate fix -- but "
            f"it makes this test's premise obsolete, so rewrite it (and this "
            f"file's module docstring) rather than widening the guard silently"
        )

    # The guard in front of File > Export > SVG, with the exact argument
    # main_window passes it. It sees nothing wrong.
    #
    # Only the SVG guard is *run*. The PNG guard probes ``cairosvg``, whose
    # import dlopens native Cairo and raises OSError where that is absent (see
    # ``_cairo_native_error``), so running it would report False on a machine
    # with no libcairo -- a second, unrelated reason to fail, on the one leg of
    # this file that already has to skip for it. The PNG guard is held to the
    # assertion above instead, which is platform-independent and is what carries
    # the teeth for it: widening it to probe PIL fails there.
    assert modules_available(svg_guard, notify=False) is True, (
        f"the SVG guard's own probe ({svg_guard}) failed with only pillow "
        f"injected as missing, so this test is not measuring what it claims to"
    )

    with pytest.raises(ModuleNotFoundError) as excinfo:
        section.exportAsSVG(str(tmp_path / "section.svg"))
    assert excinfo.value.name == "PIL"


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


# --------------------------------------------------------------------------
# 3. The export's content and ordering, against the object model.
# --------------------------------------------------------------------------
def test_export_svg_content_and_order_match_the_object_model(
        exportable_series, tmp_path):
    """Every visible trace, in ``Section.contours``' own order, geometry exact.

    ``export_svg`` reads traces from the section's columnar store; this test
    holds it to the object model's answer, path by path and in document order,
    so a flip (or a future re-flip) that changes what is exported or the order
    it is exported in fails here rather than in a viewer.

    The export walks TWO enumerations -- contour order, and trace order within
    a contour -- so the section is prepared so that a wrong answer on EITHER
    axis is DISTINGUISHABLE:

    * a trace whose contour name sorts FIRST is added LAST, so insertion order
      and sorted order disagree maximally -- reading the store's sorted
      ``contourNames()`` (or ``sorted(section.contours)``) fails the order
      assertion;
    * one contour is given THREE geometrically distinct traces, so reversing
      (or otherwise disturbing) the within-contour walk fails the content
      assertion. Every contour of the ``shapes1.jser`` fixture holds exactly
      one trace, which is why this has to be built rather than found: without
      it the inner axis has no way to be wrong in the test's material, and
      reversing ``ContourView``'s iteration leaves the whole suite green;
    * a hidden trace is added, so dropping the hidden filter fails the
      membership assertion;
    * the ``d`` attribute of every path is recomputed from the object model's
      own ``Trace.asPixels``, so geometry read from the wrong place, rounded
      differently, or pixel-mapped differently fails the content assertion.
    """
    section = exportable_series.loadSection(min(exportable_series.sections.keys()))

    template = next(iter(next(iter(section.contours.values()))))

    # A contour holding MULTIPLE traces, added first so that the two probes
    # below still land last in insertion order.
    #
    # The traces have to differ GEOMETRICALLY, not just be several: they share
    # a contour and therefore a trace name, so the id list cannot tell them
    # apart and only the `d` comparison can. Each is shifted a whole number of
    # pixels (`mag` is microns per pixel) further right than the last, which
    # survives the `int()` truncation in `point_2_pix` intact.
    #
    # The middle of the first three is then deleted and a fourth appended, so
    # the surviving order (first, third, fourth) is not creation order either:
    # a walk that reconstructed the contour from creation order, or that put a
    # deletion's survivors back in the wrong place, is visible here too.
    MULTI = "zzz_multi_trace_contour"
    created = []
    for i in range(3):
        multi_trace = template.copy()
        multi_trace.name = MULTI
        multi_trace.points = [
            (x + i * 20 * section.mag, y) for x, y in multi_trace.points
        ]
        section.addTrace(multi_trace, log_event=False)
        created.append(multi_trace)

    section.removeTrace(created[1], log_event=False)

    fourth = template.copy()
    fourth.name = MULTI
    fourth.points = [(x + 90 * section.mag, y) for x, y in fourth.points]
    section.addTrace(fourth, log_event=False)
    created.append(fourth)

    # The prepared contour really does hold three visible, pairwise-distinct
    # traces in the order the assertions below rely on. Without this the inner
    # axis' teeth could go away silently -- a fixture whose traces coincide, a
    # delete that reorders, a template that turns out hidden -- and the test
    # would go back to pinning the contour axis alone while still looking like
    # it pinned both.
    survivors = section.contours[MULTI].getTraces()
    assert [t.points for t in survivors] == [
        created[0].points, created[2].points, created[3].points
    ], "the multi-trace contour is not the three survivors in insertion order"
    assert not any(t.hidden for t in survivors), (
        "the multi-trace contour's traces are hidden, so they would be "
        "filtered out of the comparison and prove nothing"
    )
    assert len({tuple(t.points) for t in survivors}) == 3, (
        "the multi-trace contour's traces must differ geometrically, or a "
        "reversed within-contour enumeration would still match path for path"
    )

    probe = template.copy()
    probe.name = "aaa_sorts_first_added_last"
    section.addTrace(probe, log_event=False)

    hidden_probe = template.copy()
    hidden_probe.name = "aaa_hidden_probe"
    hidden_probe.setHidden(True)
    section.addTrace(hidden_probe, log_event=False)

    # The probes really did land at the END of the object model's iteration
    # order while sorting FIRST; without this the order assertion below could
    # pass under a sorted enumerator.
    assert list(section.contours)[-2:] == [
        "aaa_sorts_first_added_last", "aaa_hidden_probe"
    ]
    assert sorted(section.contours)[:2] == [
        "aaa_hidden_probe", "aaa_sorts_first_added_last"
    ]

    # The object model's own answer: (name, path data) for every visible
    # trace, contours in `section.contours` order, traces in list order.
    height, _ = section.img_dims
    mag = section.mag
    expected = []
    for contour in section.contours.values():
        for trace in contour:
            if trace.hidden:
                continue
            d = "M " + " L ".join(
                f"{x},{y}" for x, y in trace.asPixels(mag, height)
            )
            if trace.closed:
                d += " Z"
            expected.append((trace.name, d))
    assert expected, "fixture section has no visible traces; test proves nothing"

    out = tmp_path / "order.svg"
    section.exportAsSVG(str(out))

    # ElementTree iterates in document order, which is SVG paint order.
    root = ET.parse(out).getroot()
    exported = [
        (p.get("id"), p.get("d"))
        for p in root.iter(f"{{{SVG_NS}}}path")
        if p.get("id") != "scale_bar"
    ]

    assert [name for name, _ in exported] == [name for name, _ in expected], (
        "the SVG's paths are not the object model's visible traces in the "
        "object model's order"
    )
    # The within-contour axis, named separately from the whole-list comparison
    # below so that reversing (or otherwise disturbing) the trace walk inside a
    # contour reports as what it is rather than as a generic geometry mismatch.
    # The name assertion above cannot see it: these three paths share an id.
    multi_expected = [d for name, d in expected if name == MULTI]
    multi_exported = [d for name, d in exported if name == MULTI]
    assert len(multi_expected) == 3, (
        "the prepared multi-trace contour is not in the object model's answer"
    )
    assert multi_exported == multi_expected, (
        "the SVG's paths for the multi-trace contour are not in the object "
        "model's within-contour trace order"
    )

    assert exported == expected, (
        "a path's geometry differs from the object model's own asPixels answer"
    )
    assert "aaa_hidden_probe" not in {name for name, _ in exported}

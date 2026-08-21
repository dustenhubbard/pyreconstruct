# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PyReconstruct (one-folder build).

Run from the repository root, after installing the project + PyInstaller into a
Python 3.11 environment (`pip install -e .` writes PyReconstruct/_version.py):

    pyinstaller --noconfirm packaging/PyReconstruct.spec

Output:
    Windows : dist/PyReconstruct/PyReconstruct.exe
    macOS   : dist/PyReconstruct.app   (needs packaging/PyReconstruct.icns first)

NOTE on VTK: vtk is on 9.4.2, which pyinstaller-hooks-contrib covers. The explicit
hiddenimports below are kept as belt-and-suspenders to guarantee the OpenGL render
stack is bundled. If the 3D viewport ever renders blank in a frozen build, the
fallback is to build that platform via conda constructor.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# SPECPATH is the absolute path of the directory containing this spec (packaging/).
REPO_ROOT = Path(SPECPATH).parent

# --- Build flavor: packaging/FLAVOR ("dev") makes the side-by-side Dev app --
#     own name, own icons, own bundle id, and a runtime hook that stamps
#     PYRECON_APP_NAME so the app itself knows which flavor it is (update
#     channel, settings store, ownership marker, window title). No FLAVOR
#     file (the release line) builds the stable app, unchanged.
_flavor_file = REPO_ROOT / "packaging" / "FLAVOR"
IS_DEV = _flavor_file.exists() and _flavor_file.read_text().strip() == "dev"
APP_NAME = "PyReconstruct Dev" if IS_DEV else "PyReconstruct"
PKG_DIR = REPO_ROOT / "PyReconstruct"
ASSETS = PKG_DIR / "assets"
ENTRY = str(PKG_DIR / "run.py")

datas = []
binaries = []
hiddenimports = []

# --- App assets: welcome series, icons, and the helper .py scripts that run.py
#     relaunches via runpy. Bundle the tree at <_MEIPASS>/PyReconstruct/assets
#     so locations.py (frozen branch) finds it.
#
#     There is no skip list any more. The dev-only subtrees (checker/, misc/,
#     scripts/img/ and scripts/contours_from_labels/) moved out of the package
#     to dev/assets/ on 2026-08-06, so walking PyReconstruct/assets no longer
#     reaches them and the installers and the wheel ship the same code by
#     construction rather than by two skip lists agreeing with each other.
for _p in ASSETS.rglob("*"):
    if _p.is_file():
        _dest = Path("PyReconstruct/assets") / _p.relative_to(ASSETS).parent
        datas.append((str(_p), str(_dest)))

# --- setuptools-scm version file (frozen repo_info reads PyReconstruct._version)
_version_file = PKG_DIR / "_version.py"
if _version_file.exists():
    datas.append((str(_version_file), "PyReconstruct"))

# --- WHATS_NEW.md: the friendly highlights the first-launch "What's new" dialog
#     shows offline (no network). CHANGELOG.md (technical) is bundled too for
#     reference; the dialog links to the full notes on GitHub.
for _doc in ("WHATS_NEW.md", "CHANGELOG.md"):
    _p = REPO_ROOT / _doc
    if _p.exists():
        datas.append((str(_p), "PyReconstruct/assets"))

# --- VTK 9.4.2: hooks-contrib covers it; we still collect everything and force
#     the render/interaction modules as belt-and-suspenders vs a blank viewport.
_vd, _vb, _vh = collect_all("vtkmodules")
datas += _vd
binaries += _vb
hiddenimports += _vh
hiddenimports += [
    "vtkmodules.vtkRenderingOpenGL2",         # <- the key one (GL2 render factory)
    "vtkmodules.vtkRenderingFreeType",
    "vtkmodules.vtkRenderingUI",
    "vtkmodules.vtkRenderingVolumeOpenGL2",
    "vtkmodules.vtkRenderingContextOpenGL2",
    "vtkmodules.vtkRenderingAnnotation",
    "vtkmodules.vtkInteractionStyle",
    "vtkmodules.vtkInteractionWidgets",
    "vtkmodules.vtkRenderingCore",
    "vtkmodules.vtkCommonCore",
    "vtkmodules.vtkCommonDataModel",
    "vtkmodules.vtkCommonExecutionModel",
    "vtkmodules.vtkCommonMath",
    "vtkmodules.vtkCommonTransforms",
    "vtkmodules.vtkFiltersCore",
    "vtkmodules.vtkFiltersGeneral",
    "vtkmodules.vtkFiltersSources",
    "vtkmodules.vtkFiltersModeling",
    "vtkmodules.vtkIOImage",
    "vtkmodules.vtkIOXML",
    "vtkmodules.vtkIOGeometry",
    "vtkmodules.util.numpy_support",
    "vtkmodules.util.execution_model",
    "vtkmodules.qt",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
    "vtk",
]

# --- vedo data (fonts, textures, colormaps) ---
datas += collect_data_files("vedo")

# --- scipy / scikit-image: lazily-imported submodules + data files ---
#
# Both packages load their subpackages lazily -- scipy through a module-level
# __getattr__, skimage through lazy_loader stubs -- so PyInstaller's static
# analysis cannot see them and they have to be named. Naming them by collecting
# EVERY submodule (972 for scipy, 410 for skimage) is the blunt way to do that,
# and it bundles whole subpackages the app never reaches.
#
# The two lists below are the measured runtime closure, not a reading of the
# import statements: every scipy/skimage call site in PyReconstruct was
# exercised in a real interpreter and sys.modules read back afterwards. That is
# deliberate, because these packages cross-import each other internally --
# skimage.filters pulls scipy.ndimage, skimage.registration pulls
# skimage.restoration, scipy.interpolate pulls scipy.linalg/special/sparse --
# and none of that shows up in a grep of the application. Unlisted, because
# nothing reached them: scipy.io, scipy.signal, scipy.stats, scipy.integrate,
# scipy.odr, skimage.feature, skimage.graph, skimage.io, skimage.metrics.
#
# Adding a call to a scipy/skimage subpackage that is not listed here means
# adding it here too. It will not fail at launch: the frozen self-test imports
# only scipy.interpolate and skimage.draw, so a missing subpackage surfaces
# when the feature runs. Re-derive the lists by running the call sites, the
# same way these were derived, rather than by reading the imports.
#
# What this does NOT remove, and why: scipy.signal, and behind it scipy.stats
# and scipy.integrate, stay in the bundle even though the app calls none of
# them. Four skimage modules import scipy.signal at module level --
# measure/_polygon.py, filters/_window.py, restoration/deconvolution.py,
# feature/template.py -- and those sit inside subpackages the app does use, so
# the only way to drop scipy.signal would be to exclude individual skimage
# modules and leave skimage.measure.approximate_polygon, skimage.filters.window
# and skimage.restoration.richardson_lucy raising on attribute access. That is
# the hand-enumerated-transitive-dependency trap; it is not worth ~6 MB.
_SCIPY_USED = (
    "scipy._lib",         # shared helpers, imported by every subpackage below
    "scipy.cluster",      # via scipy.spatial
    "scipy.constants",    # via scipy.interpolate / skimage
    "scipy.fft",          # via scipy.fftpack and skimage.registration
    "scipy.fftpack",      # modules/calc/correlation.py (alignment correlation)
    "scipy.interpolate",  # imagej_roi.py (splprep/splev), quantification.py
    "scipy.linalg",       # via scipy.interpolate, skimage.transform
    "scipy.ndimage",      # via skimage.filters / segmentation / transform
    "scipy.optimize",     # via skimage.registration, scipy.interpolate
    "scipy.sparse",       # via scipy.interpolate, skimage.segmentation
    "scipy.spatial",      # via skimage.measure / segmentation
    "scipy.special",      # via scipy.interpolate, skimage.filters
)
_SKIMAGE_USED = (
    "skimage._shared",     # shared helpers, imported by every subpackage below
    "skimage._vendored",   # via skimage.restoration
    "skimage.color",       # autoseg palette (rgb2lab / deltaE_ciede2000)
    "skimage.data",        # imported by the subpackages below (payload trimmed)
    "skimage.draw",        # trace_layer.py, objects_3D.py, trace.py (polygon)
    "skimage.exposure",    # via skimage.filters
    "skimage.filters",     # snap_trace.py (gaussian)
    "skimage.measure",     # large_datasets.py (block_reduce)
    "skimage.morphology",  # via skimage.filters / segmentation
    "skimage.registration",# field_widget_4_data.py (phase_cross_correlation)
    "skimage.restoration", # via skimage.registration
    "skimage.segmentation",# snap_trace.py (active_contour)
    "skimage.transform",   # large_datasets.py (rescale), transform.py
    "skimage.util",        # via skimage.filters / measure / transform
)

# Neither package's own test suite is reachable from the app, but
# collect_submodules() names every test module in the subpackages above and
# PyInstaller then follows what THEY import. That is not cosmetic:
# scipy/sparse/csgraph/tests is the only thing in the entire graph that reaches
# scipy.io, and scipy.special._precompute -- a coefficient-generation helper
# that only ever runs in scipy's own development -- is one of the two things
# that reach scipy.integrate. Dropping them from hiddenimports is not enough;
# they have to be named in Analysis(excludes=...) below, which is what stops
# the static graph walk from pulling them back in.
_sci_excludes = []
for _sub in _SCIPY_USED + _SKIMAGE_USED:
    for _mod in collect_submodules(_sub):
        _parts = _mod.split(".")
        if "tests" in _parts or "_precompute" in _parts:
            if _parts[-1] in ("tests", "_precompute"):
                _sci_excludes.append(_mod)
            continue
        hiddenimports.append(_mod)

# skimage's data files are two different things under one call: the
# __init__.pyi stubs that lazy_loader reads to resolve `skimage.filters.x` at
# runtime (load-bearing -- dropping them breaks the lazy import), and ~7.5 MB of
# sample images under skimage/data/ that only skimage.data.camera() and friends
# ever open. The app calls none of those loaders, so the images are dead weight
# in every installer. Keep the stubs and the small decomposition tables
# (morphology/*.npy), drop the sample-image payload.
_SKIMAGE_SAMPLE_EXTS = {".png", ".jpg", ".jpeg", ".npy", ".npz", ".tif", ".gif", ".xml"}
for _src, _dst in collect_data_files("skimage"):
    if Path(_dst).name == "data" and Path(_src).suffix.lower() in _SKIMAGE_SAMPLE_EXTS:
        continue
    datas.append((_src, _dst))

# --- cloud-volume and its compiled codecs (best-effort; import names vary and
#     not all expose data/hooks). Failures here only affect remote-volume use.
#
#     include_py_files=False: collect_all defaults it to True, which copies each
#     package's .py sources into the bundle as loose data files on top of the
#     compiled copies already in the PYZ archive -- ~1.8 MB of duplicated source
#     across cloudvolume, numcodecs and zarr alone. Nothing in these packages
#     reads its own source at runtime; the hiddenimports and the compiled
#     binaries, which this still collects, are what the codecs actually need.
for _pkg in (
    "cloudvolume", "DracoPy", "compressed_segmentation", "fpzip",
    "compresso", "crackle", "zfpc", "numcodecs", "zarr", "fastremap",
):
    try:
        _d, _b, _h = collect_all(_pkg, include_py_files=False)
        datas += _d
        binaries += _b
        for _mod in _h:                       # same test-suite skip as above
            if "tests" in _mod.split("."):
                if _mod.split(".")[-1] == "tests":
                    _sci_excludes.append(_mod)
                continue
            hiddenimports.append(_mod)
    except Exception:
        pass

# --- trimesh data ---
datas += collect_data_files("trimesh")

# --- certifi CA bundle: a frozen app has no OS trust store, so urllib/ssl can't
#     verify TLS certificates (the in-app updater calls api.github.com). Bundle
#     certifi's cacert.pem; rthook_ssl.py points SSL_CERT_FILE at it at launch.
hiddenimports += ["certifi"]
datas += collect_data_files("certifi")

# --- Software OpenGL fallback (Windows): VTK 9's renderer needs OpenGL >= 3.2.
#     Over RDP or in a GPU-less VM the system opengl32.dll exposes only OpenGL
#     1.1, so VTK calls a null GL function pointer when the 3D viewport opens and
#     the whole app crashes (access violation at offset 0, "unknown" module).
#     Bundle Qt's software GL (Mesa llvmpipe, shipped with PySide6 as
#     opengl32sw.dll) renamed to mesa/opengl32.dll. rthook_gl.py preloads it ONLY
#     when hardware GL is inadequate (RDP session, or PYRECON_SOFTWARE_GL set), so
#     GPU machines keep fast hardware rendering.
if sys.platform.startswith("win"):
    import glob as _glob, shutil as _shutil, PySide6 as _ps6mod
    _ps6 = Path(_ps6mod.__file__).parent
    _sw = _glob.glob(str(_ps6 / "**" / "opengl32sw.dll"), recursive=True)
    if _sw:
        _mesa_dir = REPO_ROOT / "build" / "mesa_gl"
        _mesa_dir.mkdir(parents=True, exist_ok=True)
        _dst = _mesa_dir / "opengl32.dll"
        _shutil.copy(_sw[0], str(_dst))
        binaries += [(str(_dst), "mesa")]
        print(f"[spec] software-GL fallback: bundling {_sw[0]} -> mesa/opengl32.dll")
    else:
        print("[spec] WARNING: opengl32sw.dll not found under PySide6; no software-GL fallback bundled")

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[
        str(REPO_ROOT / "packaging" / "rthook_stdio.py"),  # must run first
        str(REPO_ROOT / "packaging" / "rthook_qt.py"),
        str(REPO_ROOT / "packaging" / "rthook_ssl.py"),
        str(REPO_ROOT / "packaging" / "rthook_gl.py"),
    ] + ([str(REPO_ROOT / "packaging" / "rthook_flavor.py")] if IS_DEV else []),
    excludes=[
        "PyQt5", "PyQt6", "PySide2",   # forbid clashing Qt bindings
        "tkinter",
        "matplotlib.tests",
        "cv2.qt",                       # belt-and-suspenders (we ship cv2 headless)
        # scipy/skimage/codec test suites and scipy's dev-only precompute
        # helpers, gathered above. See the comment on _sci_excludes.
        *sorted(set(_sci_excludes)),
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

is_win = sys.platform.startswith("win")
is_mac = sys.platform == "darwin"

win_icon = str(PKG_DIR / "assets" / "img" / ("PyReconstructDev.ico" if IS_DEV else "PyReconstruct.ico"))
mac_icon = str(REPO_ROOT / "packaging" / "PyReconstruct.icns")  # built by make_icns.sh (flavor-aware)
if not Path(mac_icon).exists():   # allow a local build that skipped make_icns.sh
    mac_icon = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,            # windowed (no console window)
    icon=win_icon if is_win else (mac_icon if is_mac else None),
    upx=False,                # UPX corrupts Qt/VTK shared libraries
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
    upx=False,
)

if is_mac:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=mac_icon,
        bundle_identifier=("edu.utexas.synapseweb.pyreconstruct.dev"
                           if IS_DEV else "edu.utexas.synapseweb.pyreconstruct"),
        info_plist={"NSHighResolutionCapable": True},
    )

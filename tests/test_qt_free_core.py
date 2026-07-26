"""The core data model imports no Qt (the M11 seam's endpoint).

`modules/constants` and `modules/datatypes` are the core data model. They used
to pull in Qt twice, unnecessarily: `constants/getdatetime.py` imported
`QSettings` to read the boolean "utc" preference (the *first* failure on
`import PyReconstruct.modules.datatypes`), and `datatypes/transform.py`
imported `QTransform` for four affine operations. Both now go through Qt-free
code -- the settings seam (`backend/settings_store.py`) and a plain
Python/NumPy affine -- and these tests keep it that way:

  - the capstone: in a subprocess where **any** `PySide6` import raises, the
    whole `modules.datatypes` import graph imports cleanly, `sys.modules` holds
    no `PySide6` entry afterwards, and the data model actually *works*
    (transforms map/invert/compose, timestamps are produced, traces measure);
  - the subprocess runs with `QT_QPA_PLATFORM` explicitly removed from the
    environment: no offscreen platform, no display, no Qt at all;
  - a source-level (AST) check asserts no module in `constants/` or
    `datatypes/` imports PySide6 at module scope, so a new top-level `import
    PySide6...` anywhere in the core fails here instead of silently re-tying the
    cord (the two `Transform` <-> `QTransform` adapters import Qt inside the
    function bodies, which is what keeps the module import clean);
  - the "utc" preference still round-trips through the settings seam, including
    the string form ("true"/"false") that QSettings' native backends hand back.
"""
import os
import ast
import sys
import subprocess

import pytest

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    default_settings_store,
    set_default_settings_store,
)
from PyReconstruct.modules.constants.getdatetime import utc_p

MODULES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "PyReconstruct", "modules",
)
CORE_PACKAGES = ("constants", "datatypes")


def _core_sources():
    for package in CORE_PACKAGES:
        directory = os.path.join(MODULES_DIR, package)
        for name in sorted(os.listdir(directory)):
            if name.endswith(".py"):
                yield os.path.join(directory, name)


def test_core_has_no_module_level_qt_import():
    """No module in constants/ or datatypes/ imports PySide6 at module scope.

    Function-level imports are allowed (that is how the `QTransform` adapters
    and the `QSettingsStore` default stay deferred); a top-level one is what
    breaks a headless import, so only those are rejected.
    """
    offenders = []
    for path in _core_sources():
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:  # module scope only
            targets = []
            if isinstance(node, ast.ImportFrom):
                targets = [node.module or ""]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            for target in targets:
                if target == "PySide6" or target.startswith("PySide6."):
                    offenders.append(f"{os.path.basename(path)}:{node.lineno} -> {target}")

    assert not offenders, (
        "the core data model must not import Qt at module scope:\n"
        + "\n".join(offenders)
    )


def test_datatypes_import_graph_is_qt_free():
    """Capstone: import and use the data model with all of PySide6 blocked.

    Deliberately run with NO QT_QPA_PLATFORM in the environment -- the point of
    the seam is that no Qt platform is needed at all, not that an offscreen one
    is available.
    """
    script = r"""
import sys

# drop any pre-loaded PySide6 (e.g. a dev-env sitecustomize) so the block
# governs the (re)import and this is a genuine proof in any environment
for _m in list(sys.modules):
    if _m == "PySide6" or _m.startswith("PySide6."):
        del sys.modules[_m]
for _m in list(sys.modules):
    if _m.startswith("PyReconstruct"):
        del sys.modules[_m]

class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 blocked for the Qt-free core proof")
        return None

sys.meta_path.insert(0, _BlockPySide6())

# the whole core import graph: constants (getdatetime) and datatypes (transform)
import PyReconstruct.modules.constants as constants
import PyReconstruct.modules.datatypes as datatypes
from PyReconstruct.modules.datatypes import Transform, Trace, Flag

assert not [m for m in sys.modules if m.startswith("PySide6")], (
    "importing the core data model pulled in Qt: "
    + repr([m for m in sys.modules if m.startswith("PySide6")])
)

# the affine actually works, with no Qt anywhere
t = Transform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
assert t.map(2.0, 3.0) == (1.3 * 2.0 + 0.2 * 3.0 + 4.0, -0.1 * 2.0 + 0.9 * 3.0 + 2.5)
assert t.map([(2.0, 3.0)]) == [t.map(2.0, 3.0)]
assert t.mapPointsArray([(2.0, 3.0)]).tolist() == [list(t.map(2.0, 3.0))]
back = t.inverted()
rx, ry = back.map(*t.map(2.0, 3.0))
assert abs(rx - 2.0) < 1e-9 and abs(ry - 3.0) < 1e-9
composed = t * back
assert abs(composed.det - 1.0) < 1e-9
assert abs((t * Transform.identity()).det - t.det) < 1e-12

# timestamps work: no settings backend is reachable, so the "utc" default holds
d, tm = constants.getDateTime()
assert len(d.split("-")) == 3 and ":" in tm
assert constants.get_now() is not None

# a trace measured through a transform (the datatypes <-> calc path)
trace = Trace("test", color=(1, 2, 3))
trace.points = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]
xmin, ymin, xmax, ymax = trace.getBounds(t)
assert xmin < xmax and ymin < ymax
assert isinstance(trace.getList(), list)

# a flag comment stamps itself with a date/time (getDateTime through the seam)
from PyReconstruct.modules.datatypes.flag import Comment
flag = Flag("f", 1, 2, 0, (255, 0, 0))
comment = Comment("tester", "headless")
assert comment.date and comment.time
assert comment.getList()[2:] == [comment.date, comment.time]

# still no Qt after exercising all of it
assert not [m for m in sys.modules if m.startswith("PySide6")]

print("QT_FREE_CORE_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("QT_QPA_PLATFORM", None)  # the point: no Qt platform needed
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "QT_FREE_CORE_OK" in result.stdout


def test_real_series_opens_and_maps_with_no_qt(tmp_path):
    """A real jser opens, loads a section and maps its transform, Qt blocked.

    The end-to-end version of the guarantee: series I/O, section loading and the
    affine all run with any `PySide6` import raising and no Qt platform set.
    """
    fixture = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "PyReconstruct",
        "assets", "checker", "files", "shapes1.jser",
    )
    if not os.path.exists(fixture):
        pytest.skip("fixture shapes1.jser not found")

    import shutil

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(fixture, fp)

    script = r"""
import sys

for _m in list(sys.modules):
    if _m == "PySide6" or _m.startswith("PySide6."):
        del sys.modules[_m]

class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 blocked for the Qt-free core proof")
        return None

sys.meta_path.insert(0, _BlockPySide6())

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes.series import Series

series = Series.openJser(sys.argv[1], progress=NullProgressReporter)
assert series is not None, "the series failed to open headless"
assert series.sections, "no sections loaded"

snum = sorted(series.sections.keys())[0]
section = series.loadSection(snum)
tform = section.tform
assert len(tform.getList()) == 6

# map the section's traces through its transform, both directions
for name, contour in section.contours.items():
    for trace in contour:
        pts = tform.map(trace.points)
        arr = tform.mapPointsArray(trace.points)
        assert [tuple(p) for p in arr.tolist()] == pts
        back = tform.map(pts, inverted=True)
        for (bx, by), (ox, oy) in zip(back, trace.points):
            assert abs(bx - ox) < 1e-6 and abs(by - oy) < 1e-6

series.close()

assert not [m for m in sys.modules if m.startswith("PySide6")], (
    "opening a series pulled in Qt: "
    + repr([m for m in sys.modules if m.startswith("PySide6")])
)

print("SERIES_QT_FREE_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-c", script, fp],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "SERIES_QT_FREE_OK" in result.stdout


def test_getdatetime_reads_utc_through_the_seam():
    """utc_p reads the global "utc" key from an injected store."""
    store = DictSettingsStore()
    assert utc_p(store) is False               # unset -> documented default

    store.set_value(None, "utc", True)
    assert utc_p(store) is True
    store.set_value(None, "utc", False)
    assert utc_p(store) is False

    # QSettings' native backends hand booleans back as strings on some
    # platforms/formats; both spellings must be understood
    store.set_value(None, "utc", "true")
    assert utc_p(store) is True
    store.set_value(None, "utc", "false")
    assert utc_p(store) is False

    # the key is global (code=None), not per-series
    per_series = DictSettingsStore()
    per_series.set_value("SERIESCODE", "utc", True)
    assert utc_p(per_series) is False


def test_getdatetime_uses_the_default_store_when_none_passed():
    """utc_p with no argument goes through the process-wide default store."""
    original = default_settings_store()
    store = DictSettingsStore()
    store.set_value(None, "utc", True)
    try:
        set_default_settings_store(store)
        assert default_settings_store() is store
        assert utc_p() is True
        from PyReconstruct.modules.constants import get_now
        assert get_now() is not None
    finally:
        set_default_settings_store(original)
    assert default_settings_store() is original


def test_getdatetime_honors_utc_preference():
    """get_now returns UTC or local time according to the preference."""
    from datetime import datetime, timedelta

    from PyReconstruct.modules.constants import get_now

    original = default_settings_store()
    store = DictSettingsStore()
    try:
        set_default_settings_store(store)

        store.set_value(None, "utc", True)
        assert abs((get_now() - datetime.utcnow()).total_seconds()) < 5

        store.set_value(None, "utc", False)
        assert abs((get_now() - datetime.now()).total_seconds()) < 5

        # a nonzero UTC offset makes the two branches distinguishable; skip the
        # assertion where local time *is* UTC (CI machines often run in UTC)
        offset = abs((datetime.now() - datetime.utcnow()).total_seconds())
        if offset > 60:
            store.set_value(None, "utc", True)
            utc_now = get_now()
            store.set_value(None, "utc", False)
            assert abs((get_now() - utc_now)) > timedelta(seconds=60)
    finally:
        set_default_settings_store(original)


def test_default_store_is_qsettings_backed():
    """The default is still the QSettings adapter (GUI behavior unchanged)."""
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    assert isinstance(default_settings_store(), QSettingsStore)
    assert default_settings_store() is default_settings_store()  # cached


def test_settings_store_module_needs_no_qt_to_resolve_default():
    """Resolving the default store imports no Qt (the read would)."""
    script = r"""
import sys

for _m in list(sys.modules):
    if _m == "PySide6" or _m.startswith("PySide6."):
        del sys.modules[_m]

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 blocked")
        return None

sys.meta_path.insert(0, _Block())

from PyReconstruct.modules.backend.settings_store import default_settings_store
store = default_settings_store()
assert "PySide6" not in sys.modules

# reading through it is the part that needs Qt, and it fails loudly
try:
    store.contains(None, "utc")
except ImportError:
    pass
else:
    raise AssertionError("QSettingsStore should require PySide6 to read")

# ... but utc_p degrades to the default rather than failing to timestamp
from PyReconstruct.modules.constants.getdatetime import utc_p, UTC_DEFAULT
assert utc_p() is UTC_DEFAULT
print("DEFAULT_STORE_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "DEFAULT_STORE_OK" in result.stdout

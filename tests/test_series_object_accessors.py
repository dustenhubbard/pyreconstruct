"""The ``series.objects[name]`` accessors read and write the attribute they name.

``Series.objects`` is the facade `series.py` labels "objects for non-GUI users",
and ``Objects.__getitem__`` hands back a ``SeriesObject`` whose properties are
the documented way a script reads and writes an object's attributes. Five of
those properties did not do what their name says.

Four setters called the *getter*::

    @alignment.setter
    def alignment(self, value):
        self.series.getAttr(self.name, "alignment", value)

``Series.getAttr(name, attr_name, ztrace=False)`` and
``Series.setAttr(name, attr_name, value, ztrace=False)`` take different
arguments, so ``value`` landed in ``ztrace`` and only chose which dict to
*read*. The return was discarded. Nothing was written anywhere: not to
``obj_attrs``, and not to ``ztrace_attrs`` either, which is why every test below
asserts on both dicts. A script assigning a comment, a curation status, a last
user or a per-object alignment lost the write with no error.

The four are ``alignment``, ``comment``, ``curation`` and ``last_user``. The
other two setters on the class were already correct: ``mode_3D`` calls
``setAttr``, and ``name`` goes through ``Series.editObjectAttributes``.

One getter had the mirror-image defect, and it is the worse of the two shapes
because it returns a wrong value rather than dropping a write. ``opacity_3D``
was decorated ``@mode_3D.setter``::

    @property
    def opacity_3D(self):
        return self.series.getAttr(self.name, "3D_opacity")
    @mode_3D.setter                       # <- rebuilds from mode_3D's getter
    def opacity_3D(self, value):
        return self.series.setAttr(self.name, "3D_opacity", value)

``property.setter`` returns a *new* property carrying the original's ``fget``,
so the name ``opacity_3D`` was rebound to ``mode_3D``'s getter and the plain
``@property`` two lines above it was discarded. Reading ``obj.opacity_3D``
returned the 3D mode. Measured on the unfixed tree: ``"surface"`` on an object
with nothing set, and ``"dot"`` after a mode change, where the opacity was
``0.25``. The setter half was always right, so a write-then-read probe through
the facade sees the mode string come back rather than silence.

Provenance, since the two entered separately. ``fe90fa1d`` (2023-11-09) created
``SeriesObject`` with the four setters already calling ``getObjAttr``, which
then took two arguments: the assignment raised ``TypeError`` and was loud.
``faa53ef9`` the next day renamed the pair to ``getAttr``/``setAttr`` and gave
``getAttr`` the ``ztrace`` parameter, which turned the ``TypeError`` into
today's silence. The ``opacity_3D`` decorator arrived with ``640fbc9e``
(2024-02-23), which added the property.

Every test asserts against ``series.obj_attrs``, the dict ``setAttr`` writes,
rather than reading back through the same facade. A round trip through a broken
accessor can agree with itself: the ``opacity_3D`` getter above is exactly that
case, where facade-only assertions would have passed on a wrong value.

The alignment test uses a name the series actually has. ``SeriesData.addTrace``
deliberately clears a per-object alignment that is not in ``section.tforms`` and
falls back to the series alignment, and the ``alignment`` setter calls
``series.data.refresh()`` on the line after the write. So assigning an invented
name leaves ``obj_attrs`` empty on a *fixed* tree too, and a test that used one
would pass for the wrong reason. ``no-alignment`` is in the fixture's tforms.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

OBJ = "square"


@pytest.fixture
def series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    s = Series.openJser(fp)
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


def _stored(series, attr):
    """The value in the dict ``setAttr`` writes, not the facade's view of it."""
    return series.obj_attrs.get(OBJ, {}).get(attr, "<absent>")


def _ztrace_stored(series, attr):
    return series.ztrace_attrs.get(OBJ, {}).get(attr, "<absent>")


# --------------------------------------------------------------------------- #
# one per affected setter, asserted against obj_attrs
# --------------------------------------------------------------------------- #
def test_comment_setter_writes_the_comment(series):
    assert _stored(series, "comment") == "<absent>"

    series.objects[OBJ].comment = "check this branch"

    assert series.obj_attrs[OBJ]["comment"] == "check this branch"
    assert _ztrace_stored(series, "comment") == "<absent>"


def test_last_user_setter_writes_the_user(series):
    assert _stored(series, "last_user") == "<absent>"

    series.objects[OBJ].last_user = "alice"

    assert series.obj_attrs[OBJ]["last_user"] == "alice"
    assert _ztrace_stored(series, "last_user") == "<absent>"


def test_curation_setter_writes_the_curation_triple(series):
    assert _stored(series, "curation") == "<absent>"

    series.objects[OBJ].curation = (True, "alice", "01-01-26")

    assert series.obj_attrs[OBJ]["curation"] == (True, "alice", "01-01-26")
    assert _ztrace_stored(series, "curation") == "<absent>"


def test_alignment_setter_writes_the_alignment(series):
    """``no-alignment`` is in the fixture's tforms, so the ``data.refresh()``
    on the setter's next line leaves it alone. See the module docstring."""
    section = series.loadSection(sorted(series.sections.keys())[0])
    assert "no-alignment" in section.tforms
    assert _stored(series, "alignment") == "<absent>"

    series.objects[OBJ].alignment = "no-alignment"

    assert series.obj_attrs[OBJ]["alignment"] == "no-alignment"
    assert _ztrace_stored(series, "alignment") == "<absent>"


# --------------------------------------------------------------------------- #
# the getter with the mirror-image defect
# --------------------------------------------------------------------------- #
def test_opacity_3D_reads_the_opacity_and_not_the_mode(series):
    """Written through ``Series.setAttr`` so the read is the only thing under
    test. Before the fix this returned ``"dot"``."""
    series.setAttr(OBJ, "3D_mode", "dot")
    series.setAttr(OBJ, "3D_opacity", 0.25)

    obj = series.objects[OBJ]

    assert obj.opacity_3D == 0.25
    assert obj.mode_3D == "dot"


def test_opacity_3D_default_is_the_opacity_default(series):
    """With nothing stored, ``getAttr`` defaults ``3D_opacity`` to ``1`` and
    ``3D_mode`` to ``"surface"``. Before the fix this returned ``"surface"``."""
    obj = series.objects[OBJ]

    assert obj.opacity_3D == 1
    assert obj.mode_3D == "surface"


def test_opacity_3D_setter_still_writes_the_opacity(series):
    """The setter half was never wrong; repointing the decorator must not
    change it."""
    series.objects[OBJ].opacity_3D = 0.5

    assert series.obj_attrs[OBJ]["3D_opacity"] == 0.5
    assert "3D_mode" not in series.obj_attrs.get(OBJ, {})


def test_mode_3D_is_unaffected_by_the_decorator_change(series):
    series.objects[OBJ].mode_3D = "dot"

    assert series.obj_attrs[OBJ]["3D_mode"] == "dot"
    assert "3D_opacity" not in series.obj_attrs.get(OBJ, {})

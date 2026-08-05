"""``Ztrace.color`` names two containers, not ``Sequence`` -- the same finding
as ``tests/test_trace_color_fill_mode_types.py``, applied to the third and last
holder of a stale ``color : tuple``.

``Trace`` and ``Flag`` were corrected when the colour annotation was first found
to be wrong. ``Ztrace`` carried the identical annotation and was reported at the
time rather than swept into that change, so it stayed wrong. The evidence it is
wrong is a round trip, not a hypothetical:

    ``getDict`` writes ``self.color`` straight out, JSON decodes an array to a
    ``list``, and ``fromDict`` assigns it verbatim.

So every ztrace that has been saved and reopened holds a ``list``, and nothing
normalizes it afterwards -- ``copy`` passes it through, ``getXMLObj`` only
iterates it. ``dictFromXMLObj`` reaches the same place from the other end,
building the colour as a list to scale the XML's 0-1 border to 0-255 in place.
Under ``color : tuple`` mypy called both of those a type error.

Two adjacent annotations move with it, because each feeds the constructor
directly: ``Series.createZtrace``'s ``ztrace_color`` (passed straight into
``Ztrace(...)``, and given ``trace.color`` by the field's z-tracing path) and
``Series.editZtraceAttributes``'s ``new_color`` (assigned straight to
``ztrace.color``, and read back off a ``ColorButton`` that returns the ztrace's
existing colour object untouched when the user does not pick a new one).

Widening to ``Sequence[int]`` would have been wider than right, and the cost is
invisible in an error count -- it only shows up in what stops being reported:

    ``bytes`` satisfies ``Sequence[int]``.

So under ``color : Sequence[int]``, ``Ztrace(name, b"...")`` type-checks
silently. That was caught before the widening, by the ``tuple`` annotation that
was otherwise wrong, and naming ``tuple`` and ``list`` keeps it caught.

Measured, not assumed, at mypy==2.3.0 through ``make type``: the ``Sequence``
form and the union below both report 212 errors in 16 files, so nothing was
traded for keeping the check -- but ``MYPY_PROBE`` below reports no error at all
under ``Sequence`` and reports its one expected error under the union.

No Qt required: ``ztrace`` and ``series`` are Qt-free ``datatypes`` modules,
which is why they are in mypy's scope in the first place.
"""
import inspect
import json
import typing
from collections.abc import Sequence

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.ztrace import Ztrace

COLOR_ANNOTATION = tuple[int, ...] | list[int]


def _param_annotation(func, name):
    """The annotation on parameter ``name`` of ``func``, as an object.

    ``inspect.signature`` and not ``__annotations__`` so this reads the same
    whether the annotation is written on the parameter or defaulted, and so a
    renamed parameter fails here rather than silently finding nothing.
    """
    return inspect.signature(func).parameters[name].annotation


def test_ztrace_color_annotation():
    assert _param_annotation(Ztrace.__init__, "color") == COLOR_ANNOTATION


@pytest.mark.parametrize(
    "func, param",
    [
        (Series.createZtrace, "ztrace_color"),
        (Series.editZtraceAttributes, "new_color"),
    ],
)
def test_series_ztrace_color_params_agree_with_the_constructor(func, param):
    """The two that feed ``Ztrace.color`` have to say what it says.

    ``createZtrace`` passes its argument straight into ``Ztrace(...)`` and
    ``editZtraceAttributes`` assigns its argument straight to ``ztrace.color``,
    so a narrower annotation on either one goes on rejecting a live caller after
    the constructor itself has been corrected -- which is exactly how correcting
    ``Trace`` alone put an error into ``section.py`` by way of ``Flag``.
    """
    assert _param_annotation(func, param) == COLOR_ANNOTATION


def test_createztrace_default_is_unchanged_by_the_widening():
    """Widening the annotation must not have disturbed the actual default."""
    assert inspect.signature(Series.createZtrace).parameters["ztrace_color"].default == (0, 0, 0)


def test_union_members_are_concrete_containers():
    """Exactly two members, both concrete, neither abstract.

    This is the assertion that actually forbids the regression. An abstract
    member -- ``Sequence``, ``Iterable``, ``Collection`` -- is what lets
    ``bytes`` back in; naming ``tuple`` and ``list`` cannot.
    """
    assert typing.get_args(COLOR_ANNOTATION) == (tuple[int, ...], list[int])


def test_bytes_is_a_sequence_but_is_not_tuple_or_list():
    """The membership fact the union exists to exclude, checked rather than
    asserted in a comment.

    If this ever stops being true of the interpreter, the reasoning above stops
    applying and ``Sequence`` would have been fine after all -- so it is worth a
    runtime check rather than a claim.
    """
    assert isinstance(b"\x00\x01\x02", Sequence)
    assert not isinstance(b"\x00\x01\x02", (tuple, list))


@pytest.mark.parametrize("color", [(255, 0, 0), [255, 0, 0]])
def test_both_containers_survive_the_jser_round_trip(color):
    """The union is not too narrow, and the premise really is a round trip.

    A tuple colour comes back a list, which is the whole reason the ``tuple``
    annotation was wrong -- so this pins the premise rather than the annotation.
    Runtime behaviour is unchanged by any of this: annotations are never
    consulted at runtime in this tree.
    """
    ztrace = Ztrace("zt", color, [(1.0, 2.0, 0)])

    saved = json.loads(json.dumps({"zt": ztrace.getDict()}))
    restored = Ztrace.fromDict("zt", saved["zt"])

    assert list(restored.color) == list(color)
    assert isinstance(restored.color, list), "a reopened ztrace holds a list"
    assert isinstance(restored.copy().color, list), "and copy() passes it through"


def test_dictfromxmlobj_builds_the_colour_as_a_list():
    """The other live caller that hands ``Ztrace`` a list.

    Duck-typed rather than a real ``ZContour``: this pins the container the
    conversion produces, which is what the annotation is about, and needs no
    legacy XML machinery to do it.
    """

    class _XMLZContour:
        name = "zt"
        border = (1.0, 0.0, 0.0)
        points = [(1.0, 2.0, 0)]

    d = Ztrace.dictFromXMLObj(_XMLZContour())

    assert isinstance(d["color"], list)
    assert d["color"] == [255, 0, 0]


# The probe the finding was measured with, kept verbatim. Lines 3 and 4 must be
# accepted -- the list one is the whole point of the widening -- and line 6 must
# be rejected, which is what ``Sequence`` would have given up.
MYPY_PROBE = '''\
from PyReconstruct.modules.datatypes.ztrace import Ztrace

z = Ztrace("ok-list", [1, 2, 3])
w = Ztrace("ok-tuple", (1, 2, 3))

Ztrace("bytes", b"\\x00\\x01\\x02")
'''

MYPY_PROBE_EXPECTED_ERROR_LINES = (6,)


def test_probe_under_mypy(tmp_path):
    """The direct evidence, when a type checker is available to give it.

    Skipped in the default test environment on purpose rather than by accident:
    mypy is pinned with ``--with mypy==2.3.0`` in the ``type`` job and the
    Makefile, outside ``uv.lock``, so ``--extra test`` does not carry it. The
    runtime assertions above are what hold the line in CI; this is the
    corroboration for anyone who runs it with mypy present.
    """
    api = pytest.importorskip("mypy.api")

    probe = tmp_path / "probe_ztrace_color.py"
    probe.write_text(MYPY_PROBE, encoding="utf-8")

    stdout, _stderr, _status = api.run(
        [
            "--no-color-output",
            "--follow-imports=silent",
            "--python-version=3.11",
            str(probe),
        ]
    )

    error_lines = {
        int(line.split(":")[1])
        for line in stdout.splitlines()
        if ": error:" in line and line.startswith(str(probe))
    }
    assert error_lines == set(MYPY_PROBE_EXPECTED_ERROR_LINES), stdout

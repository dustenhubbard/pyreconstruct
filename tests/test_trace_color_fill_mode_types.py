"""``Trace.color`` / ``Trace.fill_mode`` / ``Flag.color`` name two containers,
not ``Sequence``.

These three were annotated ``tuple``, which called the ordinary ``.jser`` round
trip a type error: ``fromList`` assigns a colour verbatim from parsed JSON,
where an array decodes to a ``list``, and ``Section``'s import paths
(``addImportFlag``, plus the two inline constructions in ``importTraces``)
build a ``Flag`` straight out of ``trace.color``. Widening them was right.
Widening them to ``Sequence`` was wider than right, and the cost is not visible
from the error count -- it only shows up in what stops being reported:

    ``str`` satisfies ``Sequence[str]`` and ``bytes`` satisfies ``Sequence[int]``.

So under ``fill_mode : Sequence[str]``, ``trace.fill_mode = "solid"`` -- a bare
string where a (mode, mode) pair belongs -- type-checks silently, and under
``color : Sequence[int]`` so does ``Trace(name, b"...")``. Both were caught
before the widening, by the ``tuple`` annotation that was otherwise wrong.
Measured: at the pre-widening tree those two lines are errors, under
``Sequence`` they are not, and under the union spelled below they are again --
with the same total mypy count as ``Sequence`` gave, so nothing was traded for
them.

The union is therefore load-bearing in a way an error count cannot show, which
is what this file is for. The assertions are runtime ones: they pin the exact
annotation objects, and they demonstrate the ``str``/``bytes`` membership fact
that is the whole reason for spelling the union out. ``test_probe_under_mypy``
adds the direct type-checker evidence when mypy is importable, which it is not
in the test extra -- mypy is pinned into the ``type`` job and the Makefile with
``--with``, deliberately outside ``uv.lock``.

No Qt required: ``trace`` and ``flag`` are Qt-free ``datatypes`` modules, which
is why they are in mypy's scope in the first place.
"""
import inspect
import typing
from collections.abc import Sequence

import pytest

from PyReconstruct.modules.datatypes.flag import Flag
from PyReconstruct.modules.datatypes.trace import Trace

COLOR_ANNOTATION = tuple[int, ...] | list[int]
FILL_MODE_ANNOTATION = tuple[str, ...] | list[str]


def _param_annotation(func, name):
    """The annotation on parameter ``name`` of ``func``, as an object.

    ``inspect.signature`` and not ``__annotations__`` so this reads the same
    whether the annotation is written on the parameter or defaulted, and so a
    renamed parameter fails here rather than silently finding nothing.
    """
    return inspect.signature(func).parameters[name].annotation


def test_trace_fill_mode_annotation():
    """The class-body annotation is the two containers, spelled out."""
    assert Trace.__annotations__["fill_mode"] == FILL_MODE_ANNOTATION


def test_trace_color_annotation():
    assert _param_annotation(Trace.__init__, "color") == COLOR_ANNOTATION


def test_flag_color_annotation():
    """``Flag`` moves with ``Trace``: ``addImportFlag`` feeds one the other.

    ``Section.addImportFlag`` -- and the two inline constructions in
    ``Section.importTraces`` -- build a ``Flag`` out of ``trace.color``, so
    correcting ``Trace`` alone put an error *into* ``section.py`` rather than
    taking one out: ``trace.color`` then arrived at a ``Flag`` whose own
    annotation still said ``tuple``. The two have to agree.
    """
    assert _param_annotation(Flag.__init__, "color") == COLOR_ANNOTATION


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (FILL_MODE_ANNOTATION, (tuple[str, ...], list[str])),
        (COLOR_ANNOTATION, (tuple[int, ...], list[int])),
    ],
)
def test_union_members_are_concrete_containers(annotation, expected):
    """Exactly two members, both concrete, neither abstract.

    This asserts on the module's own constants, so no edit to ``trace.py`` or
    ``flag.py`` can reach it and it is *not* what forbids the regression --
    measured: it passes under the ``Sequence`` mutation. What forbids the
    regression is the annotation pins above, which read the real annotation
    object off the source and compare it against these constants; this test
    keeps those constants honest, so loosening one to make a failing pin pass
    is caught here instead. An abstract member -- ``Sequence``, ``Iterable``,
    ``Collection`` -- is what lets ``str`` and ``bytes`` back in; naming
    ``tuple`` and ``list`` cannot.
    """
    assert typing.get_args(annotation) == expected


def test_str_and_bytes_are_sequences_but_are_not_tuple_or_list():
    """The membership fact the union exists to exclude, checked rather than
    asserted in a comment.

    If this ever stops being true of the interpreter, the reasoning above stops
    applying and ``Sequence`` would have been fine after all -- so it is worth a
    runtime check rather than a claim.
    """
    assert isinstance("solid", Sequence)
    assert isinstance(b"\x00\x01\x02", Sequence)
    assert not isinstance("solid", (tuple, list))
    assert not isinstance(b"\x00\x01\x02", (tuple, list))


@pytest.mark.parametrize("color", [(255, 0, 0), [255, 0, 0]])
@pytest.mark.parametrize("fill_mode", [("none", "none"), ["solid", "transparent"]])
def test_both_containers_still_round_trip(color, fill_mode):
    """The union is not too narrow: tuple *and* list survive ``getList`` ->
    ``fromList``, which is the shape the widening existed to admit.

    Runtime behaviour here is unchanged by any of this -- annotations are never
    consulted at runtime in this tree -- so this pins the premise, not the
    annotation: a list colour really is a shape the round trip produces, so an
    annotation that rejects one really is wrong.
    """
    trace = Trace("obj", color)
    trace.fill_mode = fill_mode

    restored = Trace.fromList(trace.getList(include_name=True))

    assert list(restored.color) == list(color)
    assert list(restored.fill_mode) == list(fill_mode)


# The probe the finding was measured with, kept verbatim. Line 1 and 2 must be
# accepted -- they are the whole point of the widening -- and lines 3 to 5 must
# be rejected, which is what ``Sequence`` gave up.
MYPY_PROBE = '''\
from PyReconstruct.modules.datatypes.flag import Flag
from PyReconstruct.modules.datatypes.trace import Trace

t = Trace("ok-list", [1, 2, 3])
t.fill_mode = ["solid", "none"]

t.fill_mode = "solid"
Trace("bytes", b"\\x00\\x01\\x02")
Flag("f", 1, 2, 3, b"\\x00\\x01\\x02")
'''

MYPY_PROBE_EXPECTED_ERROR_LINES = (7, 8, 9)


def test_probe_under_mypy(tmp_path):
    """The direct evidence, when a type checker is available to give it.

    Skipped in the default test environment on purpose rather than by accident:
    mypy is pinned with ``--with mypy==2.3.0`` in the ``type`` job and the
    Makefile, outside ``uv.lock``, so ``--extra test`` does not carry it. The
    runtime assertions above are what hold the line in CI; this is the
    corroboration for anyone who runs it with mypy present.
    """
    api = pytest.importorskip("mypy.api")

    probe = tmp_path / "probe_trace_color.py"
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

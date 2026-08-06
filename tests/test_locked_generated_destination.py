"""A generated destination name can land traces in a locked object.

Two operations pick their own destination instead of asking for one:

    Series.copyObjects   writes into `<name>_copy`
    Series.splitObject   writes into `<name>_1` .. `<name>_N`

Neither generator looks for a free name. `<name>_copy` collides on the second
copy of the same object, which is a two-step user recipe: copy `star`, lock
`star_copy`, copy `star` again. `<name>_NN` collides on any series that already
numbers objects that way, which is the ordinary manual convention. When the
object sitting on that name is locked, the operation adds traces to it, and
adding traces is exactly what lock exists to prevent (`specs/lock-semantics.md`:
locking prevents mutations that would change quantitative data).

Nothing caught this. The field's `object_function` decorator does check for
locked objects, but it checks the objects the *user selected*, which are the
sources and are unlocked. `refuseLockedTraces` reads the objects the selected
traces are in now, same blind spot. The destination is generated after every one
of those checks has passed.

Measured on `shapes1.jser` before the fix: copying `star` into a locked
`star_copy` took it from 5 traces to 10, and splitting `star` into a locked
`star_1` took that from 1 trace to 2.

The refusal is keyed on the destination name being locked, and on nothing else.
It deliberately does not change how the names are generated: copying twice into
an *unlocked* `star_copy` still merges, exactly as it always has, and
`test_a_second_copy_into_an_unlocked_copy_still_merges` is the guard against a
future fix quietly turning that into `star_copy_copy`. Lock is the only new
input.

All-or-nothing, matching `refuseLockedTraces` and `object_function`: one locked
destination refuses the whole call rather than doing the rest, so nobody ends up
with half a copy or a half-split object.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)

SOURCE = "star"      # 5 traces, one per section
OTHER = "square"     # a second object to donate traces from
COPY = "star_copy"   # what copyObjects generates for SOURCE

# What splitObject generates for SOURCE, written out rather than recomputed:
# `star` has 5 traces, so the width is one digit. Recomputing it from the same
# formula the code uses would make the test agree with the code by construction.
SPLIT_NAMES = ["star_1", "star_2", "star_3", "star_4", "star_5"]

REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."


def open_fixture(tmp_path, name="s"):
    """A real Series opened from a private copy of the checked-in fixture.

    `shapes1.jser` rather than `conftest.py`'s `real_series`: that one is
    `class_series.jser` (198 sections), and these tests copy and split whole
    objects several times over.
    """
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")

    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)

    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


def count(series, name):
    """Traces named `name` across the whole series."""
    total = 0

    for _, section in series.enumerateSections(show_progress=False):
        if name in section.contours:
            total += len(section.contours[name])

    return total


def plant(series, name, donor=OTHER):
    """Make an object called `name` exist, by copying a donor's traces to it.

    The collision needs a real object on the generated name, not just an
    `obj_attrs` entry: the assertions are about traces that did or did not move
    into it.
    """
    for _, section in series.enumerateSections(show_progress=False):
        if donor in section.contours:
            for trace in section.contours[donor].getTraces():
                planted = trace.copy()
                planted.name = name
                section.addTrace(planted, log_event=False)
            section.save()
            break

    assert count(series, name) > 0

    return count(series, name)


# --- copyObjects --------------------------------------------------------------

def test_a_locked_copy_destination_refuses_the_copy(series):
    """Copy, lock the copy, copy again. The second copy must not land."""
    assert series.copyObjects([SOURCE]) == [COPY]
    before = count(series, COPY)
    assert before == 5

    series.setAttr(COPY, "locked", True)

    assert series.copyObjects([SOURCE]) == []
    assert count(series, COPY) == before
    assert count(series, SOURCE) == 5
    assert f"{COPY}_copy" not in series.data["objects"]


def test_a_second_copy_into_an_unlocked_copy_still_merges(series):
    """The unlocked collision is untouched: it merges, as it always has.

    Here so the refusal cannot quietly grow into a rule about collisions. The
    only new input is the lock.
    """
    series.copyObjects([SOURCE])
    assert count(series, COPY) == 5

    assert series.copyObjects([SOURCE]) == [COPY]
    assert count(series, COPY) == 10


def test_copying_is_unaffected_by_a_lock_somewhere_else(series):
    """The ordinary copy, with a locked object elsewhere in the same series."""
    series.setAttr(OTHER, "locked", True)

    assert series.copyObjects([SOURCE]) == [COPY]
    assert count(series, COPY) == 5
    assert count(series, OTHER) > 0


def test_one_locked_destination_refuses_the_whole_selection(series):
    """All-or-nothing on a multi-object copy, like every other lock check."""
    series.copyObjects([OTHER])
    series.setAttr(f"{OTHER}_copy", "locked", True)

    assert series.copyObjects([SOURCE, OTHER]) == []
    assert COPY not in series.data["objects"]


def test_copy_destinations_are_named_before_the_copy_runs(series):
    """`copyObjectNames` is what the guard, the return value and the field share."""
    assert series.copyObjectNames([SOURCE, OTHER]) == [COPY, f"{OTHER}_copy"]
    assert series.copyObjects([SOURCE, OTHER]) == series.copyObjectNames(
        [SOURCE, OTHER]
    )


# --- splitObject --------------------------------------------------------------

def test_splitting_produces_one_object_per_trace(series):
    """The normal path, and the source of the names the collision tests use."""
    assert series.splitObject(SOURCE) == set(SPLIT_NAMES)
    assert count(series, SOURCE) == 0

    for name in SPLIT_NAMES:
        assert count(series, name) == 1


def test_a_locked_split_destination_refuses_the_split(series):
    """An object already named `star_1`, and locked, stops the split."""
    planted = plant(series, SPLIT_NAMES[0])
    series.setAttr(SPLIT_NAMES[0], "locked", True)

    assert series.splitObject(SOURCE) == set()
    assert count(series, SPLIT_NAMES[0]) == planted
    assert count(series, SOURCE) == 5  # the source is not emptied either
    assert SPLIT_NAMES[1] not in series.data["objects"]


def test_a_lock_on_a_later_split_name_refuses_it_too(series):
    """All-or-nothing: the collision does not have to be the first name."""
    plant(series, SPLIT_NAMES[3])
    series.setAttr(SPLIT_NAMES[3], "locked", True)

    assert series.splitObject(SOURCE) == set()
    assert count(series, SOURCE) == 5
    assert SPLIT_NAMES[0] not in series.data["objects"]


def test_splitting_is_unaffected_by_a_lock_somewhere_else(series):
    """A locked object that no generated name collides with changes nothing."""
    series.setAttr(OTHER, "locked", True)

    assert series.splitObject(SOURCE) == set(SPLIT_NAMES)
    assert count(series, OTHER) > 0


def test_split_destinations_are_named_before_the_split_runs(series):
    """`splitObjectNames` must agree with what the split actually creates."""
    assert series.splitObjectNames(SOURCE) == SPLIT_NAMES
    assert series.splitObjectNames("no_such_object") == []


# --- the field, so the refusal is not a command that does nothing -------------

@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from the object field widget.

    It binds `notify` into its own namespace with `from ... import notify`, so
    patching the helper at its source has no effect. Required, not just
    convenient: offscreen, `notify` falls through to a console branch ending in
    `input()`, which raises `EOFError` under pytest's capture.
    """
    from PyReconstruct.modules.gui.main import field_widget_3_object

    notices = []
    monkeypatch.setattr(
        field_widget_3_object,
        "notify",
        lambda message, *a, **kw: notices.append(message),
    )

    return notices


# Two objects that both live on section 52 of `class_series.jser`, which is the
# section the window opens on. The same pair the other locked-destination tests
# use, and both hold 5 traces, so a split of either is numbered to one digit.
GUI_SOURCE = "d03p14"
GUI_SPLIT_SOURCE = "d03sp14"


def selected(field, traces):
    field.section.selected_traces.clear()

    for trace in traces:
        field.section.addSelectedTrace(trace)

    assert field.section.selected_traces


def on_section(field, name):
    contours = field.section.contours

    return len(contours[name]) if name in contours else 0


@pytest.mark.gui
def test_field_copy_refuses_a_locked_copy_destination(
    main_window, main_window_dialogs, field_notices
):
    """The recipe a user can run: copy, lock the copy, copy again."""
    field = main_window.field
    destination = f"{GUI_SOURCE}_copy"

    existing = field.section.contours[GUI_SOURCE][0].copy()
    existing.name = destination
    field.section.addTrace(existing, log_event=False)
    main_window.series.setAttr(destination, "locked", True)

    selected(field, [field.section.contours[GUI_SOURCE][0]])
    before = on_section(field, destination)

    field.copyObjects()

    assert on_section(field, destination) == before
    assert REFUSAL in field_notices


@pytest.mark.gui
def test_field_split_refuses_a_locked_split_destination(
    main_window, main_window_dialogs, field_notices
):
    """`d03sp14` has 5 traces, so the first name the split wants is `d03sp14_1`."""
    field = main_window.field
    destination = f"{GUI_SPLIT_SOURCE}_1"

    existing = field.section.contours[GUI_SPLIT_SOURCE][0].copy()
    existing.name = destination
    field.section.addTrace(existing, log_event=False)
    main_window.series.setAttr(destination, "locked", True)

    selected(field, [field.section.contours[GUI_SPLIT_SOURCE][0]])
    before_source = on_section(field, GUI_SPLIT_SOURCE)
    before = on_section(field, destination)

    field.splitObject()

    assert on_section(field, destination) == before
    assert on_section(field, GUI_SPLIT_SOURCE) == before_source
    assert REFUSAL in field_notices


@pytest.mark.gui
def test_field_copy_without_a_collision_still_copies(
    main_window, main_window_dialogs, field_notices
):
    """The ordinary copy through the field, refusing nothing."""
    field = main_window.field
    destination = f"{GUI_SOURCE}_copy"

    selected(field, [field.section.contours[GUI_SOURCE][0]])
    source_traces = on_section(field, GUI_SOURCE)

    field.copyObjects()

    assert on_section(field, destination) == source_traces
    assert REFUSAL not in field_notices

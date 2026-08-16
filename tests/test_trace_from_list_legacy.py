"""``Trace.fromList`` row parsing: input mutation, and the legacy history field.

Two separate things are covered here, and only one of them is a fix.

**Fixed: ``fromList`` mutated the row it was given.** The name was read with
``l.pop(0)``, so parsing a 9-field row consumed its first element. The same
row could not be parsed twice -- the second call saw 8 fields with ``x`` where
the name belonged and raised ``ValueError: not enough values to unpack``. The
damage is worse than a failed second parse, because rows are not always
throwaway: ``Series.getDefaultPaletteTraces`` iterates the module-level
``default_traces`` constant, and had to pass ``l.copy()`` to avoid destroying
that constant for the remainder of the process. That defensive copy is the
evidence the trap was known; it is now unnecessary (and harmless -- it is left
in place, since removing it is not this change's business).

**Not fixed, deliberately: the legacy per-trace history field is dropped.** It
is asserted here as current behavior, not as desired behavior, so that the
loss is pinned rather than merely believed, and so it cannot change silently.

What the audit trail claimed was "the 9th per-trace history field is silently
dropped, and ``getList`` cannot round-trip it". Verified against the code, that
is right about the drop and wrong about the position, and "silently" needs
qualifying:

  * The 9th element of a *section contour* row is ``tags``, not history.
    History was a **trailing** field, so a section row carrying it has 9
    elements (8 + history) and a *palette* row carrying it has 10
    (9 + history). Two arities, one field.
  * It is not dropped in ``fromList`` at all. It is dropped one layer earlier,
    by the format upgraders -- ``Section.updateJSON`` (``trace.pop()`` on a
    9-element row) and ``Series.updateJSON`` (``trace.pop()`` on a 10-element
    one) -- each with an explicit ``# remove history from trace if it exists``
    comment. The drop is a deliberate, commented migration, not an accident.
  * ``Trace`` has no ``history`` attribute, so ``getList`` genuinely cannot
    round-trip the field. That is consistent with the drop rather than an
    additional bug: there is nowhere for the value to live.

Preserving it is not attempted, because it is a schema decision and not a code
fix. Giving ``Trace`` a ``history`` field would make ``getList(include_name=
False)`` emit 9 elements, which is exactly the arity ``fromList`` currently
uses to mean "name-bearing row" -- so the round trip cannot be added without
first re-deciding how row shapes are discriminated. And the project already
has a successor mechanism: ``LogSet``/``Log`` records dated, attributed,
per-object, per-section history at series level, which is a strict superset of
what a per-trace string held. Whether the legacy field should be migrated into
the log, preserved verbatim, or left dropped is the maintainer's call. See the
PR body.
"""

import pytest

from PyReconstruct.modules.constants import default_traces
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import Series


def _row9(name="mito"):
    """A name-bearing row: what ``getList(include_name=True)`` produces."""
    return [
        name,                       # 0 name
        [0.0, 1.0, 1.0],            # 1 x
        [0.0, 0.0, 1.0],            # 2 y
        [255, 0, 0],                # 3 color
        True,                       # 4 closed
        False,                      # 5 negative
        False,                      # 6 hidden
        ["none", "none"],           # 7 fill_mode
        ["tagA"],                   # 8 tags
    ]


def _row8():
    """A nameless row: what ``getList(include_name=False)`` produces."""
    return _row9()[1:]


# --------------------------------------------------------------------------
# the fix: parsing a row must not consume it
# --------------------------------------------------------------------------

def test_from_list_does_not_mutate_a_name_bearing_row():
    row = _row9()
    before = list(row)

    Trace.fromList(row)

    assert row == before, "fromList consumed part of its input row"


def test_from_list_does_not_mutate_a_nameless_row():
    row = _row8()
    before = list(row)

    Trace.fromList(row, "mito")

    assert row == before, "fromList consumed part of its input row"


def test_same_row_can_be_parsed_twice():
    """The direct symptom: a reused row used to raise on the second parse."""
    row = _row9()

    first = Trace.fromList(row)
    second = Trace.fromList(row)

    assert first.name == second.name == "mito"
    assert first.points == second.points
    assert first.tags == second.tags == {"tagA"}


def test_default_traces_constant_survives_repeated_parsing():
    """The live hazard the defensive ``.copy()`` in Series was guarding.

    ``default_traces`` is a module-level constant of 9-field rows. Parsing it
    without copying used to strip a field from every row permanently, so the
    second pass over the palette defaults saw malformed data.
    """
    snapshot = [list(row) for row in default_traces]

    for row in default_traces:
        Trace.fromList(row)
    for row in default_traces:
        Trace.fromList(row)

    assert [list(row) for row in default_traces] == snapshot


def test_round_trip_through_get_list_is_stable():
    """A parsed row re-serializes to the row it came from, both arities."""
    row9 = _row9()
    assert Trace.fromList(row9).getList(include_name=True) == row9

    row8 = _row8()
    assert Trace.fromList(row8, "mito").getList(include_name=False) == row8


# --------------------------------------------------------------------------
# unchanged behavior, pinned so the fix is provably behavior-preserving
# --------------------------------------------------------------------------

def test_nine_field_row_still_self_names_over_a_passed_name():
    """Load-bearing: ``FieldState.getContours`` relies on the embedded name."""
    trace = Trace.fromList(_row9("mito"), "ignored_name")

    assert trace.name == "mito"


def test_eight_field_row_without_a_name_still_raises():
    """No new tolerance introduced: this was, and remains, a ValueError.

    An 8-field row is meaningless without a name, and no caller passes one
    that way. It is pinned only to show the fix did not quietly turn a hard
    failure into a trace named after its own x-coordinates.
    """
    with pytest.raises(ValueError):
        Trace.fromList(_row8())


# --------------------------------------------------------------------------
# the legacy history field: documented loss, asserted as-is
# --------------------------------------------------------------------------

HISTORY = "2020-01-01 someuser created"


def test_trace_has_no_history_attribute():
    trace = Trace.fromList(_row9())

    assert not hasattr(trace, "history")


def test_section_upgrade_drops_the_trailing_history_field():
    """A 9-element *section* row is 8 fields + history; the history is popped."""
    row = _row8() + [HISTORY]
    assert len(row) == 9

    section_data = Section.getEmptyDict()
    section_data["contours"] = {"mito": [row]}

    Section.updateJSON(section_data, 0)

    upgraded = section_data["contours"]["mito"][0]
    assert len(upgraded) == 8
    assert HISTORY not in upgraded
    assert upgraded == _row8(), "the eight surviving fields must be untouched"

    # and the field is unrecoverable from the resulting Trace
    trace = Trace.fromList(upgraded, "mito")
    assert HISTORY not in trace.getList(include_name=True)


def test_series_upgrade_drops_the_trailing_history_field_from_palette_rows():
    """A 10-element *palette* row is 9 fields + history; the history is popped."""
    row = _row9() + [HISTORY]
    assert len(row) == 10

    series_data = Series.getEmptyDict()
    series_data["palette_traces"] = [row]

    Series.updateJSON(series_data)

    palettes = series_data["palette_traces"]
    # the same upgrader also wraps a bare list into the named-palette dict
    upgraded = palettes["palette1"][0] if isinstance(palettes, dict) else palettes[0]

    assert len(upgraded) == 9
    assert HISTORY not in upgraded
    assert upgraded == _row9()


def test_history_is_not_what_the_ninth_section_field_is():
    """Guards against the mis-reading that motivated this investigation.

    The 9th element of a name-bearing row is ``tags``. Anyone "restoring"
    history by reading index 8 would be reading the tag list.
    """
    row = _row9()

    assert row[8] == ["tagA"]
    assert Trace.fromList(row).tags == {"tagA"}

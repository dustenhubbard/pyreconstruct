"""The per-object mutators must load only the sections holding the objects.

``Series._forEachObjectSection`` passes
``section_numbers=self.getObjectSections(obj_names)`` into
``enumerateSections``, and that one line now carries the section scoping for
all seven converted mutators. Nothing else in the suite pins it. Deleting it
leaves the rest of the suite green *and* leaves an on-disk equivalence digest
byte-identical, because the ``edit`` callback returns falsy for sections the
objects are absent from, so widening the scope produces no extra save and
nothing reaches disk differently.

The only observable difference is how many sections get loaded: on the
checked-in 198-section fixture, an object living on a single section goes from
1 load to 198. That is the entire point of the scoping, and it is invisible to
both instruments the refactor was checked with -- so measure it directly.

``SeriesIterator.__next__`` obtains every section through
``Series.loadSection``, so counting calls to that method counts exactly the
sections a mutator visits. The assertion is the equality the scoping claims:
visited == ``getObjectSections``, no more and no less. ``SPARSE_OBJECT`` is
deliberately an object on one section out of 198, so the equality has teeth --
an object present everywhere would satisfy it under the mutation too, which
``test_the_scoping_assertion_can_fail`` guards against by construction.
"""
import pytest

from PyReconstruct.modules.datatypes import Series


# On class_series.jser this object has traces on exactly one of the 198
# sections, which is the widest possible gap between scoped and unscoped.
SPARSE_OBJECT = "Test1DenShaft"


# Every public method that routes through Series._forEachObjectSection, called
# the way the field widget calls it. The lambda takes (series, name) so the
# object under test is chosen in one place.
CONVERTED_MUTATORS = {
    "deleteObjects": lambda s, n: s.deleteObjects([n]),
    "deleteAllTraces": lambda s, n: s.deleteAllTraces(n),
    "editObjectRadius": lambda s, n: s.editObjectRadius([n], 0.5),
    "editObjectShape": lambda s, n: s.editObjectShape(
        [n], [(0, 0), (1, 0), (1, 1), (0, 1)]
    ),
    "removeAllTraceTags": lambda s, n: s.removeAllTraceTags([n]),
    "reapplyAutosegColors": lambda s, n: s.reapplyAutosegColors([n]),
    "hideObjects": lambda s, n: s.hideObjects([n], True),
}


@pytest.fixture
def loaded_sections(monkeypatch):
    """Record every section number Series.loadSection is asked for."""
    visited = []
    original = Series.loadSection

    def counting_loadSection(self, section_num):
        visited.append(section_num)
        return original(self, section_num)

    monkeypatch.setattr(Series, "loadSection", counting_loadSection)
    return visited


@pytest.mark.parametrize("mutator_name", sorted(CONVERTED_MUTATORS))
def test_converted_mutator_visits_only_the_object_sections(
    real_series, loaded_sections, mutator_name
):
    """Each converted mutator loads the object's sections and nothing else."""
    series = real_series
    expected = series.getObjectSections([SPARSE_OBJECT])

    # The fixture must actually discriminate: if the object were on every
    # section, dropping the scoping would be undetectable here.
    assert expected, f"{SPARSE_OBJECT} is missing from the fixture"
    assert len(expected) < len(series.sections), (
        "the object under test must be sparse for this assertion to have "
        f"teeth: {len(expected)} of {len(series.sections)} sections"
    )

    CONVERTED_MUTATORS[mutator_name](series, SPARSE_OBJECT)

    assert set(loaded_sections) == expected, (
        f"{mutator_name} visited {sorted(set(loaded_sections))}, but "
        f"{SPARSE_OBJECT} is only on {sorted(expected)}. Dropping "
        "section_numbers=self.getObjectSections(...) from "
        "Series._forEachObjectSection makes every one of these methods walk "
        "the whole series."
    )
    assert len(loaded_sections) == len(expected), (
        f"{mutator_name} loaded {len(loaded_sections)} sections for "
        f"{len(expected)} distinct section numbers -- a section was loaded "
        "more than once"
    )


def test_the_sparse_object_really_is_sparse(real_series):
    """Pin the premise the parametrized assertions rest on.

    If a future edit to the fixture spread SPARSE_OBJECT across every section,
    the equality above would still pass with the scoping deleted. This makes
    that failure loud instead of silent.
    """
    scoped = real_series.getObjectSections([SPARSE_OBJECT])
    assert len(scoped) == 1, (
        f"{SPARSE_OBJECT} is expected on exactly one section of the fixture; "
        f"found {sorted(scoped)}"
    )
    assert len(real_series.sections) > 100, (
        "the fixture is expected to have many sections, so that scoped and "
        "unscoped iteration differ by a wide margin"
    )

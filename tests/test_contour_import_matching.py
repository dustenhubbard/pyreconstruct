"""Contour imports match reordered duplicates once and retain unmatched traces."""

import pytest

from PyReconstruct.modules.datatypes import Contour, Trace


def square(x, tag):
    trace = Trace("axon", (10, 20, 30), closed=True)
    trace.points = [(x, 0), (x + 10, 0), (x + 10, 10), (x, 10)]
    trace.tags = {tag}
    return trace


@pytest.mark.parametrize("keep", ["self", "other", ""])
def test_reordered_import_keeps_unmatched_traces_and_merges_duplicate_tags(keep):
    current = Contour("axon", [square(0, "local-only"), square(20, "local"), square(40, "local")])
    incoming = Contour("axon", [square(40.1, "incoming"), square(20.1, "incoming"), square(60, "incoming-only")])

    local_conflicts, incoming_conflicts = current.importTraces(incoming, keep_above=keep)

    assert [list(t.points)[0] for t in local_conflicts] == [(0, 0)]
    assert [list(t.points)[0] for t in incoming_conflicts] == [(60, 0)]
    if keep == "":
        assert [(list(t.points)[0][0], t.tags) for t in current] == [
            (40, {"local"}), (40.1, {"incoming"}),
            (20, {"local"}), (20.1, {"incoming"}),
            (0, {"local-only"}), (60, {"incoming-only"}),
        ]
    else:
        expected_xs = [40, 20, 0, 60] if keep == "self" else [40.1, 20.1, 0, 60]
        assert [list(t.points)[0][0] for t in current] == expected_xs
        assert [t.tags for t in current] == [
            {"local", "incoming"}, {"local", "incoming"},
            {"local-only"}, {"incoming-only"},
        ]


def test_one_incoming_trace_cannot_consume_two_local_duplicates():
    current = Contour("axon", [square(0, "unmatched"), square(20, "first"), square(20, "second")])
    incoming = Contour("axon", [square(20, "incoming")])

    local_conflicts, incoming_conflicts = current.importTraces(incoming)

    assert [(list(t.points)[0][0], t.tags) for t in current] == [
        (20, {"first", "incoming"}), (0, {"unmatched"}), (20, {"second"}),
    ]
    assert [t.tags for t in local_conflicts] == [{"unmatched"}, {"second"}]
    assert incoming_conflicts == []

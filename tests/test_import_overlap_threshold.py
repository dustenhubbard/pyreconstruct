"""Regression tests for the overlap threshold used by Contour.importTraces.

Contour.importTraces matches traces in two passes:

  1. an optimistic pass that walks self[i] against other[i] while they overlap,
  2. a nested scan over everything left over -- i.e. over exactly the traces
     that genuinely diverged between the two series.

The caller-supplied ``threshold`` was honoured in pass 1 but pass 2 compared
with a literal ``threshold=0.95``. Every trace pair that a merge actually has
to reason about is decided in pass 2, so a user who moved the "Overlap
threshold" slider off its default silently got 0.95 for the only comparisons
that mattered. Both directions of the discrepancy are damaging:

  * threshold > 0.95 (user asked for stricter matching): two traces that are
    NOT duplicates at the requested threshold are merged anyway, and with the
    default ``keep_above="self"`` the importing series' trace is dropped
    outright -- silent loss of the other person's annotation.
  * threshold < 0.95 (user asked for looser matching): two traces that ARE
    duplicates at the requested threshold are kept as a conflicting pair,
    producing a duplicate trace and a spurious conflict flag.

Geometry: two axis-aligned side-10 squares offset along x by ``dx`` have
Jaccard index (10-dx)/(10+dx) once rasterised. dx=0.2 -> ~0.961 and dx=0.5 ->
~0.913, which straddle 0.95 from either side. Each test asserts the ratio it
depends on, so a change in the overlap primitive fails loudly instead of
quietly invalidating the premise.
"""
import pytest

from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.trace import Trace


def mk(dx, tag=None, side=10.0, dy=0.0):
    """A closed square of the given side, offset by (dx, dy)."""
    t = Trace("o", (0, 0, 0), True)
    t.points = [
        (dx, dy), (dx + side, dy), (dx + side, dy + side), (dx, dy + side)
    ]
    if tag:
        t.addTag(tag)
    return t


FAR = 500.0  # far enough away that nothing overlaps it


def _remainder_pair(dx):
    """Build (self, other) contours whose only candidate pair lands in pass 2.

    ``self`` leads with a decoy that overlaps nothing, so the optimistic pass
    breaks immediately and the real pair (self[1] vs other[0]) can only be
    resolved by the nested remainder scan.
    """
    s_decoy = mk(FAR)
    s_trace = mk(0.0, tag="drawn_by_A")
    o_trace = mk(dx, tag="drawn_by_B")
    return (
        Contour("o", [s_decoy, s_trace]),
        Contour("o", [o_trace]),
        s_trace,
        o_trace,
    )


def test_remainder_scan_honours_a_stricter_threshold():
    """At threshold=0.99 a ~0.96 pair is not a duplicate, so neither trace may
    be discarded."""
    s, o, s_trace, o_trace = _remainder_pair(0.2)
    assert 0.95 < s_trace.getOverlapRatio(o_trace) < 0.99, "premise: ratio straddles 0.95 and 0.99"

    rem_s, rem_o = s.importTraces(o, threshold=0.99, keep_above="self")

    assert len(s) == 3, "no pair overlaps at 0.99, so all three traces survive"
    assert any(t is o_trace for t in s), (
        "the importing series' trace was silently dropped: it was treated as a "
        "duplicate at 0.95 even though the caller asked for 0.99"
    )
    assert o_trace in rem_o, "it must also be reported as an unresolved conflict"
    assert "drawn_by_B" not in s_trace.tags, "no tag merge should have happened"


def test_remainder_scan_honours_a_looser_threshold():
    """At threshold=0.91 a ~0.913 pair IS a duplicate and must be collapsed."""
    s, o, s_trace, o_trace = _remainder_pair(0.5)
    assert 0.91 < s_trace.getOverlapRatio(o_trace) < 0.95, "premise: ratio straddles 0.91 and 0.95"

    rem_s, rem_o = s.importTraces(o, threshold=0.91, keep_above="self")

    assert len(s) == 2, "the duplicate pair should collapse to one trace plus the decoy"
    assert not any(t is o_trace for t in s), "keep_above='self' keeps self's trace"
    assert "drawn_by_B" in s_trace.tags, "the duplicate's tags must be absorbed"
    assert rem_o == [], "a resolved duplicate is not a conflict"


def test_both_passes_agree_on_the_threshold():
    """The same pair must be classified identically whether it is resolved by
    the optimistic pass or by the remainder scan."""
    for threshold, dx in ((0.99, 0.2), (0.91, 0.5), (0.95, 0.2), (0.95, 0.5)):
        # pass 1: the pair is at index 0 in both contours
        s1 = Contour("o", [mk(0.0)])
        o1 = Contour("o", [mk(dx)])
        s1.importTraces(o1, threshold=threshold, keep_above="self")
        merged_in_pass_1 = (len(s1) == 1)

        # pass 2: a leading decoy forces the same pair through the remainder scan
        s2, o2, _, _ = _remainder_pair(dx)
        s2.importTraces(o2, threshold=threshold, keep_above="self")
        merged_in_pass_2 = (len(s2) == 2)  # decoy + one merged trace

        assert merged_in_pass_1 == merged_in_pass_2, (
            f"threshold={threshold} dx={dx}: optimistic pass and remainder scan "
            f"disagree (pass1 merged={merged_in_pass_1}, pass2 merged={merged_in_pass_2})"
        )


def test_skipped_first_comparison_is_only_the_known_false_pair():
    """The remainder scan skips its very first comparison on the grounds that
    the optimistic pass already proved that pair does not overlap. Pin that
    invariant: the skip must not eat a comparison that could have matched.

    self  = [A, B]   other = [A', B']  with A~A' and B~B' at the threshold, but
    other stored in the opposite order, so the optimistic pass breaks at i=0
    and both genuine matches have to be found by the remainder scan.
    """
    A, B = mk(0.0), mk(0.0, dy=FAR)
    A2, B2 = mk(0.2), mk(0.2, dy=FAR)
    s = Contour("o", [A, B])
    o = Contour("o", [B2, A2])

    assert not A.overlaps(B2, 0.95), "premise: the leading pair does not overlap"

    rem_s, rem_o = s.importTraces(o, threshold=0.95, keep_above="self")

    assert len(s) == 2, "both pairs are duplicates and must collapse"
    assert rem_s == [] and rem_o == [], "nothing should be left unresolved"


def test_threshold_of_one_requires_an_exact_match_in_the_remainder_scan():
    """threshold=1.0 is documented as "points must match perfectly". A merge
    must not quietly relax that for the divergent traces."""
    s, o, s_trace, o_trace = _remainder_pair(0.2)
    s.importTraces(o, threshold=1.0, keep_above="self")
    assert any(t is o_trace for t in s), (
        "at threshold=1.0 a ~0.96 overlap is not an exact match; the importing "
        "series' trace must be preserved"
    )


def test_keep_other_does_not_discard_self_below_the_threshold():
    """With keep_above='other' a false duplicate match discards *self's* trace,
    so the threshold bug loses work in that direction too."""
    s, o, s_trace, o_trace = _remainder_pair(0.2)
    s.importTraces(o, threshold=0.99, keep_above="other")
    assert any(t is s_trace for t in s), (
        "the current series' own trace was discarded on a match that should not "
        "have happened at threshold=0.99"
    )

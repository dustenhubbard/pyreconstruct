"""Regression test for Ztrace's mutable default points argument.

Ztrace.__init__ declared ``points : list = []``. A default argument is created
once and shared, so two ztraces constructed without an explicit points list
alias the same underlying list -- appending to one leaks into the other. This
is the same defect class as the createZtrace fix; harden the constructor with a
None sentinel. (Callers that pass points explicitly are unaffected, as is
dictFromXMLObj, which reassigns .points immediately after construction.)
"""
from PyReconstruct.modules.datatypes.ztrace import Ztrace


def test_ztraces_without_points_do_not_share_a_list():
    z1 = Ztrace("a", (0, 0, 0))
    z2 = Ztrace("b", (0, 0, 0))

    z1.points.append((1.0, 1.0, 0))

    assert z2.points == [], "ztraces must not share a default points list"
    assert z1.points is not z2.points


def test_explicit_points_are_used():
    pts = [(1.0, 2.0, 0), (3.0, 4.0, 1)]
    z = Ztrace("a", (0, 0, 0), pts)
    assert z.points == pts

"""Regression test for Log.trimSectionRange's malformed list.append call.

One branch did ``new_section_ranges.append(srange[0], s2)`` -- two positional
args to list.append (which takes one), raising TypeError. The three sibling
branches correctly append a tuple; this one was missing its inner parens. The
branch is reached whenever a stored range starts at section 0 (so ``s1`` is
falsy and the ``if s1 and ...`` guard skips it) but its end falls inside the
import range -- a realistic case, since section 0 is every series' first
section. Reached from histories.importLogs during a trace-history import.
"""
from PyReconstruct.modules.datatypes.log import Log


def _log(section_ranges):
    return Log("24-01-01", "1200", "u", "obj", section_ranges, "modified")


def test_trim_range_starting_at_zero():
    # stored range (0, 30); import range (5, 51) -> hits the s2-only branch
    log = _log([(0, 30)])

    result = log.trimSectionRange((5, 51))  # previously raised TypeError

    assert result is True
    assert log.section_ranges == [(5, 30)]


def test_trim_range_fully_inside_import_range():
    # both endpoints inside -> the s1-truthy branch keeps the range as-is
    log = _log([(10, 20)])

    assert log.trimSectionRange((5, 51)) is True
    assert log.section_ranges == [(10, 20)]


def test_trim_range_end_outside_import_range():
    # s1 inside, s2 outside -> clamped to srange[1] - 1
    log = _log([(10, 60)])

    assert log.trimSectionRange((5, 51)) is True
    assert log.section_ranges == [(10, 50)]


def test_trim_empty_section_ranges():
    log = _log([])

    assert log.trimSectionRange((5, 51)) is True
    assert log.section_ranges == [(5, 50)]

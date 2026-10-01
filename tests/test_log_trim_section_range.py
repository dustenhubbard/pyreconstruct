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


# The first branch used to test `if s1 and s2 in sections`, which Python reads
# as `s1 and (s2 in sections)`. A nonzero start passed whenever the end was in
# range, so (2, 7) survived an import of 5 to 9 untrimmed. A start of section 0
# never passed and fell to the next branch, which stretched the end to the end
# of the import range.

def test_trim_start_before_import_range():
    log = _log([(2, 7)])

    assert log.trimSectionRange((5, 10)) is True
    assert log.section_ranges == [(5, 7)]


def test_range_from_section_zero_inside_import_range_is_kept():
    log = _log([(0, 1)])

    assert log.trimSectionRange((0, 5)) is True
    assert log.section_ranges == [(0, 1)]


def test_range_outside_import_range_is_dropped():
    log = _log([(0, 1)])

    assert log.trimSectionRange((5, 10)) is False
    assert log.section_ranges == [(0, 1)]


def test_import_history_through_import_traces(tmp_path):
    """The same through `Series.importTraces` with a section range."""
    import shutil

    from conftest import SERIES_FIXTURE
    from PyReconstruct.modules.datatypes import Series

    paths = []
    for name in ("self", "other"):
        p = tmp_path / name / "series.jser"
        p.parent.mkdir()
        shutil.copy(SERIES_FIXTURE, p)
        paths.append(p)
    s_self = Series.openJser(str(paths[0]))
    s_other = Series.openJser(str(paths[1]))
    try:
        s_other.user = "colleague"
        for n in range(2, 8):
            s_other.addLog("axon_probe", n, "Modify trace(s)")
        for n in (0, 1):
            s_other.addLog("dend_probe", n, "Modify trace(s)")
        s_other.save()

        s_self.importTraces(s_other, srange=(5, 10))  # sections 5 to 9

        def ranges(name):
            return [
                l.section_ranges
                for l in s_self.getFullHistory().all_logs
                if l.obj_name == name
            ]

        assert ranges("axon_probe") == [[(5, 7)]]
        assert ranges("dend_probe") == []
    finally:
        s_self.close()
        s_other.close()

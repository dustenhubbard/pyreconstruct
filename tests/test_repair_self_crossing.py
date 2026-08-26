"""Series > Clean up > Repair self-crossing traces.

Autoseg emits closed traces whose outline crosses itself, usually a
zero-width spike doubling back over its own edge (Patrick's report,
2026-08-25, with a one-pixel example), and a crossed outline blocks the
scalpel. The repair keeps the trace's real loop and discards the artifact.

The safety rule under test is his option 1 (2026-08-25): repair only when
the discarded loops are tiny beside the kept one. A genuine figure 8 with
two real loops is skipped for the scissors, because keeping one loop would
silently delete the other.
"""

import pytest

from PyReconstruct.modules.calc import repair_self_crossing

pytestmark = pytest.mark.gui

# A square whose boundary runs up a zero-width spike and back: exactly the
# autoseg artifact from the report. Invalid as a polygon, one real loop.
SPIKED_SQUARE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
    (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
    (0.0, 10.0),
]

# A bowtie with two equal loops: a genuine figure 8, never auto-repaired.
EQUAL_BOWTIE = [(0.0, 0.0), (10.0, 0.0), (0.0, 8.0), (10.0, 8.0)]


# --------------------------------------------------------------------------
# the calc layer
# --------------------------------------------------------------------------

def test_spike_is_repaired_to_the_real_loop():
    from shapely.geometry import Polygon

    assert not Polygon(SPIKED_SQUARE).is_valid          # the premise
    repaired = repair_self_crossing(SPIKED_SQUARE)
    assert repaired is not None
    fixed = Polygon(repaired)
    assert fixed.is_valid
    assert fixed.area == pytest.approx(100.0)           # the square survived
    assert (5.0, 10.5) not in repaired                  # the spike did not


def test_equal_loops_are_left_for_the_scissors():
    assert repair_self_crossing(EQUAL_BOWTIE) is None


def test_valid_and_degenerate_traces_are_untouched():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert repair_self_crossing(square) is None         # valid: nothing to do
    assert repair_self_crossing(square[:2]) is None     # not a polygon at all


def test_the_ratio_is_the_dial():
    """The same bowtie flips from skipped to repaired when the caller accepts
    a bigger discard, which pins the rule to the ratio and nothing else."""
    lopsided = [(0.0, 0.0), (10.0, 0.0), (2.0, 3.0), (10.0, 3.0)]
    assert repair_self_crossing(lopsided, max_discard_ratio=0.01) is None
    assert repair_self_crossing(lopsided, max_discard_ratio=0.9) is not None


# --------------------------------------------------------------------------
# the series layer, on a real series
# --------------------------------------------------------------------------

@pytest.fixture
def series_with_spike(real_series):
    """A writable series carrying one spiked trace on its first section."""
    from PyReconstruct.modules.datatypes import Trace

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    trace = Trace("f8_spike_test", (255, 0, 0), closed=True)
    trace.points = list(SPIKED_SQUARE)
    section.addTrace(trace, log_event=False)
    section.save()
    return real_series, snum


def test_scan_finds_the_spike_and_calls_it_repairable(series_with_spike):
    series, snum = series_with_spike
    records = series.findSelfCrossingTraces()
    ours = [r for r in records if r["name"] == "f8_spike_test"]
    assert len(ours) == 1
    assert ours[0]["section"] == snum
    assert ours[0]["repairable"] is True


def test_repair_fixes_the_saved_trace(series_with_spike):
    from shapely.geometry import Polygon

    series, snum = series_with_spike
    records = [
        r for r in series.findSelfCrossingTraces() if r["name"] == "f8_spike_test"
    ]
    repaired = series.repairSelfCrossingTraces(records)
    assert [r["name"] for r in repaired] == ["f8_spike_test"]

    section = series.loadSection(snum)                  # fresh from disk
    traces = list(section.contours["f8_spike_test"])
    assert len(traces) == 1
    assert Polygon(traces[0].points).is_valid
    assert Polygon(traces[0].points).area == pytest.approx(100.0)


def test_locked_objects_are_never_scanned(series_with_spike):
    series, snum = series_with_spike
    series.setAttr("f8_spike_test", "locked", True)
    records = series.findSelfCrossingTraces()
    assert not [r for r in records if r["name"] == "f8_spike_test"]


def test_unrepairable_records_are_not_applied(series_with_spike):
    """A repairable=False record passed in anyway (a stale or hand-built
    list) must not be touched."""
    series, snum = series_with_spike
    records = [
        r for r in series.findSelfCrossingTraces() if r["name"] == "f8_spike_test"
    ]
    records[0]["repairable"] = False
    assert series.repairSelfCrossingTraces(records) == []


# --------------------------------------------------------------------------
# The two review windows around the pass (his asks, 2026-08-26): skipped
# looped traces get an actionable list, repaired ones get a summary. Both
# inherit navigation, copy-to-clipboard and save-as-CSV from the malformed-
# contours review dialog, so only what is specific here is tested.
# --------------------------------------------------------------------------

def _looped_record():
    return {
        "name": "figure8", "section": 4, "index": 0, "points": 4,
        "location": (1.0, 2.0), "reason": "Outline crosses itself",
        "match": {"color": (255, 0, 0), "points": []}, "repairable": False,
    }


def test_skipped_dialog_navigates_and_copies(qapp, gui_dialogs):
    from PySide6.QtWidgets import QApplication, QPushButton
    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        SkippedCrossingsDialog,
    )

    visited = []
    dialog = SkippedCrossingsDialog(
        None, [_looped_record()],
        navigate=lambda snum, name, index: visited.append((snum, name)),
    )
    try:
        assert "scissors" in dialog._headingText()
        dialog.table.selectRow(0)
        dialog._navigateToRow(0)
        assert visited == [(4, "figure8")]

        labels = [b.text() for b in dialog.findChildren(QPushButton)]
        assert "Copy table list" in labels
        assert any(label.startswith("Save table as CSV") for label in labels)

        dialog.copyToClipboard()
        assert "figure8" in QApplication.clipboard().text()
    finally:
        dialog.deleteLater()


def test_repaired_dialog_summarizes_with_the_same_roads(qapp, gui_dialogs):
    from PySide6.QtWidgets import QPushButton
    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        RepairedCrossingsDialog,
    )

    record = dict(_looped_record(), repairable=True)
    dialog = RepairedCrossingsDialog(None, [record], navigate=lambda *a: None)
    try:
        heading = dialog._headingText()
        assert "Repaired 1 self-crossing trace" in heading
        assert "one undo" in heading
        labels = [b.text() for b in dialog.findChildren(QPushButton)]
        assert "Copy table list" in labels
        assert any(label.startswith("Save table as CSV") for label in labels)
    finally:
        dialog.deleteLater()


def test_the_repair_prompt_builds_without_error(qapp, main_window, gui_dialogs, monkeypatch):
    """The confirm prompt crashed live with NameError: the undo-chord helper
    was used at line 3519 with no import in scope, and no test drove the
    prompt itself (his error report, 2026-08-26). This one does: a spiked
    trace goes in, the prompt must reach notifyConfirm and decline safely."""
    from PyReconstruct.modules.datatypes import Trace
    import PyReconstruct.modules.gui.main.main_window as mw

    series = main_window.series
    snum = sorted(series.sections)[0]
    section = series.loadSection(snum)
    trace = Trace("prompt_spike", (255, 0, 0), closed=True)
    trace.points = [
        (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
        (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
        (0.0, 10.0),
    ]
    section.addTrace(trace, log_event=False)
    section.save()

    prompts = []
    monkeypatch.setattr(
        mw, "notifyConfirm", lambda text, yn=True: prompts.append(text) or False
    )
    main_window.repairSelfCrossingTraces()      # raised NameError before

    assert prompts, "the confirm prompt never built"
    assert "This can be undone (" in prompts[0]
    assert "Ctrl+Z" not in prompts[0] or "Cmd" not in prompts[0]

"""The clean-up lists open with one line and a `?` that holds the rest.

Each window that lists traces to check (smoothing, scissors, repaired,
pixel dust, duplicates) used to open with paragraphs above the list. Now the
heading is one short line that says what the list holds, and the `?` next to
it carries the full explanation as its tooltip, unchanged.
"""
import pytest

pytestmark = pytest.mark.gui

from PyReconstruct.modules.gui.dialog.malformed_contours import (
    DuplicateTracesDialog,
    MalformedContoursDialog,
    PixelDustDialog,
    RepairedCrossingsDialog,
    SkippedCrossingsDialog,
)


def _record(**extra):
    record = {
        "name": "OBJ", "section": 1, "index": 0, "points": 2,
        "location": (0.0, 0.0), "reason": "Too few points",
        "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
        "area": 1e-4, "area_px": 3.0, "repairable": False,
    }
    record.update(extra)
    return record


def _group():
    members = [_record(name="A"), _record(name="B", index=1)]
    return {
        "section": 1, "members": members, "names": ["A", "B"], "count": 2,
        "ratio": 0.97, "location": (0.0, 0.0),
    }


# (dialog factory, the one line it opens with, a sentence from the old
# explanation that now lives in the tooltip)
CASES = {
    "smoothing": (
        lambda: MalformedContoursDialog(None, [_record(), _record(name="B")]),
        "2 traces could not be smoothed.",
        "A trace is skipped when it cannot be smoothed",
    ),
    "scissors": (
        lambda: SkippedCrossingsDialog(None, [_record()]),
        "1 self-crossing trace to fix with the scissors.",
        "cut out the crossing with the scissors tool",
    ),
    "repaired": (
        lambda: RepairedCrossingsDialog(None, [_record(), _record()]),
        "Repaired 2 self-crossing traces.",
        "the crossing artifact was removed",
    ),
    "pixel dust": (
        lambda: PixelDustDialog(None, [_record()], delete=lambda recs: []),
        "1 trace at or below the pixel-area threshold.",
        "Nothing is removed until you choose to delete.",
    ),
    "duplicates": (
        lambda: DuplicateTracesDialog(None, [_group()], combine=lambda c: []),
        "1 structure traced more than once.",
        "Pick the name to keep in each row.",
    ),
}


@pytest.fixture(params=list(CASES), ids=list(CASES))
def case(request, qtbot):
    make, line, explained = CASES[request.param]
    dialog = make()
    qtbot.addWidget(dialog)
    return dialog, line, explained


def test_the_heading_is_one_short_line(case):
    dialog, line, _ = case
    assert dialog.heading.text() == line
    assert "\n" not in dialog.heading.text()


def test_the_question_mark_holds_the_full_explanation(case):
    dialog, _, explained = case
    assert dialog.help_icon.text() == "?"
    tip = dialog.help_icon.toolTip()
    assert explained in tip
    # every paragraph of the explanation is in the tooltip, as rich text so
    # Qt wraps it instead of drawing one very wide line
    for paragraph in dialog._explanationText().split("\n\n"):
        assert paragraph.replace("&", "&amp;") in tip
    assert tip.startswith("<p>")


def test_the_question_mark_sits_next_to_the_line_above_the_list(case, qtbot):
    dialog, _, _ = case
    dialog.show()
    qtbot.waitExposed(dialog)
    heading = dialog.heading.geometry()
    icon = dialog.help_icon.geometry()
    table = dialog.table.geometry()
    assert dialog.help_icon.isVisible()
    assert icon.left() >= heading.right()
    assert abs(icon.center().y() - heading.center().y()) <= 4
    assert icon.bottom() < table.top()
    assert heading.bottom() < table.top()


def test_the_line_and_tooltip_follow_a_delete(qtbot):
    record = _record()
    dialog = PixelDustDialog(None, [record], delete=lambda recs: list(recs))
    qtbot.addWidget(dialog)

    # what a confirmed Delete does once the series has dropped the trace
    dialog._pruneRecords([record])

    assert dialog.heading.text() == (
        "All listed traces have been deleted. You can close this window."
    )
    assert "All listed traces have been deleted." in (
        dialog.help_icon.toolTip()
    )


def test_the_keyboard_can_open_the_explanation(case, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolTip

    dialog, _, _ = case
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.help_icon.focusPolicy() & Qt.TabFocus
    assert dialog.help_icon.accessibleName() == "Explanation"

    dialog.help_icon.setFocus()
    qtbot.keyClick(dialog.help_icon, Qt.Key_Space)

    qtbot.waitUntil(QToolTip.isVisible)
    assert QToolTip.text() == dialog.help_icon.toolTip()
    QToolTip.hideText()

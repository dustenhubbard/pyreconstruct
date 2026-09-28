"""Undo for "Delete from sections..." (fork issue #422), through the real window.

The changelog entry and the reply on the issue both say undo brings the traces
back. This is the test behind that sentence. It drives the action the way the
user does: select the object's traces on the open section, run the field
action, answer the section picker, then undo.

Two cases, because `MainWindow.undo()` takes two different roads. A delete that
leaves the open section alone records a series-wide state only, and undo takes
it directly. A delete that includes the open section also leaves a linked
section-only state, and undo asks "All sections" or "Only this section" (see
tests/test_linked_undo_headless.py).
"""

import pytest

pytestmark = pytest.mark.gui

# Traces on 182 of 198 fixture sections, including the one the window opens on.
OBJECT = "d03"


@pytest.fixture
def window(main_window, monkeypatch):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    main_window.series.setProgressReporter(NullProgressReporter)
    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))
    main_window.notices = notices
    yield main_window
    main_window.series.setProgressReporter(None)


def sections_carrying(series, name):
    return [
        snum
        for snum, section in series.enumerateSections(show_progress=False)
        if name in section.contours and len(section.contours[name])
    ]


def delete_from(window, monkeypatch, chosen):
    """Select OBJECT on the open section and delete it from `chosen`."""
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    class Picker:
        def __init__(self, *a, **k):
            self.kw = k

        def get(self):
            return set(chosen), True

    monkeypatch.setattr(fw2, "CopyToSectionsDialog", Picker)
    section = window.field.section
    section.selected_traces = list(section.contours[OBJECT])
    window.field.deleteTracesFromSections()


def test_undo_restores_a_delete_away_from_the_open_section(
    window, main_window_dialogs, monkeypatch
):
    current = window.series.current_section
    before = sections_carrying(window.series, OBJECT)
    chosen = [s for s in before if s != current][:5]
    assert len(chosen) == 5

    delete_from(window, monkeypatch, chosen)

    after = sections_carrying(window.series, OBJECT)
    assert after == [s for s in before if s not in chosen], (
        "the delete touched sections outside the chosen set"
    )
    assert current in after
    assert any(m.startswith("Deleted trace(s) from sections") for m in window.notices)

    window.undo()

    assert sections_carrying(window.series, OBJECT) == before


def test_undo_all_sections_restores_a_delete_that_includes_the_open_section(
    window, main_window_dialogs, monkeypatch
):
    current = window.series.current_section
    before = sections_carrying(window.series, OBJECT)
    assert current in before
    chosen = [current] + [s for s in before if s != current][:3]

    delete_from(window, monkeypatch, chosen)
    window.saveAllData()
    assert sections_carrying(window.series, OBJECT) == [
        s for s in before if s not in chosen
    ]

    main_window_dialogs.linked_undo_responses.append("all")
    window.undo()

    assert sections_carrying(window.series, OBJECT) == before

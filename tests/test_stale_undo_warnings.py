"""Pins the audit of "WARNING: This action cannot be undone."

Background. `noUndoWarning()` (`PyReconstruct/modules/gui/utils/utils.py`) is the
single source of that message. It was once shown on nearly every list action;
`7e013e29` ("Fully implement series undo/redo for list actions and imports")
gave those actions real undo states and deleted the warning from them at the
same time. Three call sites survived that cleanup, and all three are still
correct. The user-facing manual, however, was never updated, so it still tells
users that editing object attributes and object radii cannot be undone and that
Undo does not reach the lists at all. Those claims are false.

What these tests hold in place:

1. The set of `noUndoWarning()` call sites, exactly. Parsed out of the source, so
   a new caller fails the test and has to be justified, and deleting one of the
   three genuinely destructive ones fails it too.
2. That the two surviving list callers really are gated on the warning: declining
   it must abort. If the warning were dropped from either, declining would let
   the destructive action run and these tests would catch it.
3. That `optimizeBC` is gated the same way. Driven unbound against a stub,
   because the warning lives on `MainWindow` and the real widget cannot be built
   headless.
4. That the three object edits the wishlist names (attributes, radius, shape) do
   record series undo states. This is the factual basis for the doc change: the
   manual's claim is not merely out of date in tone, it is measurably wrong.
5. That the manual no longer makes the false claims, and does still warn about
   deleting a section, which remains irreversible.

Not covered here: whether the dialogs look right on screen. That needs a click.
"""
import ast
import pathlib
import shutil
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "PyReconstruct"
MANUAL = REPO_ROOT / "manual" / "readme.md"

FIXTURE = REPO_ROOT / "PyReconstruct" / "assets" / "checker" / "files" / "shapes1.jser"

# The call sites the audit found, and the reason each one is right to keep.
#
#   MainWindow.optimizeBC      writes new brightness/contrast onto every
#                              selected section and saves it. No series_states
#                              is threaded through optimizeSeriesBC, so nothing
#                              is recorded.
#   deleteSections             os.remove()s the section files, then calls
#                              field.clearStates(), which throws the undo stack
#                              away outright.
#   reorderSections            renumbers every section, then clearStates() too.
EXPECTED_CALL_SITES = {
    ("PyReconstruct/modules/gui/main/main_window.py", "MainWindow.optimizeBC"),
    ("PyReconstruct/modules/gui/table/section.py",
     "SectionTableWidget.deleteSections"),
    ("PyReconstruct/modules/gui/table/section.py",
     "SectionTableWidget.reorderSections"),
}


# ---------------------------------------------------------------------------
# 1. the call-site set itself
# ---------------------------------------------------------------------------

def _undo_warning_call_sites():
    """Every `noUndoWarning(...)` call in the package, as (path, qualname).

    Source-level rather than import-level on purpose: importing every GUI
    module to introspect it would need a QApplication and would miss nothing
    that `ast` misses.
    """
    found = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(REPO_ROOT).as_posix()
        scope = []

        class Visitor(ast.NodeVisitor):
            def _scoped(self, node):
                scope.append(node.name)
                self.generic_visit(node)
                scope.pop()

            visit_FunctionDef = _scoped
            visit_AsyncFunctionDef = _scoped
            visit_ClassDef = _scoped

            def visit_Call(self, node):
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name == "noUndoWarning":
                    found.add((relative, ".".join(scope)))
                self.generic_visit(node)

        Visitor().visit(tree)
    return found


def test_undo_warning_call_sites_are_exactly_the_destructive_three():
    """The warning appears on three paths, and they are the three that earn it.

    A failure here is not necessarily a bug, but it is always a decision: either
    a path grew a warning it does not need (the wishlist complaint), or one of
    the three lost a warning it does need.
    """
    assert _undo_warning_call_sites() == EXPECTED_CALL_SITES


def test_the_warning_helper_has_one_definition_and_one_message():
    """One helper, so rewording it is a single edit and greps stay reliable."""
    utils = (PACKAGE_ROOT / "modules" / "gui" / "utils" / "utils.py").read_text(
        encoding="utf-8"
    )
    assert utils.count("def noUndoWarning") == 1
    assert utils.count("WARNING: This action cannot be undone.") == 1


def test_no_module_inlines_the_warning_text_instead_of_calling_the_helper():
    """A path that spells the message out by hand would dodge the audit above."""
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "utils.py" and path.parent.name == "utils":
            continue  # the definition itself
        text = path.read_text(encoding="utf-8")
        if "cannot be undone." in text and "noUndoWarning" not in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []


# ---------------------------------------------------------------------------
# 2. the two section-list callers are really gated on it
# ---------------------------------------------------------------------------

def test_declining_the_warning_does_not_delete_sections(
    unlocked_section_table, gui_dialogs
):
    """Answering "cancel" to the warning leaves every section on disk.

    The companion test in test_section_list_real_widget.py covers the accepting
    path (the recorder returns True by default). Together they show the warning
    is not decoration: it decides whether the delete happens.
    """
    widget = unlocked_section_table
    gui_dialogs.undo_warning_accepted = False
    series = widget.series
    before = sorted(series.sections)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.deleteSections()

    assert sorted(series.sections) == before


def test_declining_the_warning_does_not_reorder_sections(
    unlocked_section_table, gui_dialogs
):
    """Same gate on "Reorder sections", which also clears the undo stack."""
    widget = unlocked_section_table
    gui_dialogs.undo_warning_accepted = False
    series = widget.series
    before = sorted(series.sections)

    widget.reorderSections()

    assert sorted(series.sections) == before


# ---------------------------------------------------------------------------
# 3. optimizeBC, unbound against a stub
# ---------------------------------------------------------------------------

class _OptimizeBCStub:
    """The MainWindow surface `optimizeBC` touches, and nothing else."""

    def __init__(self, section_numbers):
        self.series = types.SimpleNamespace(
            sections={n: f"s{n}" for n in section_numbers},
            window=[0, 0, 10, 10],
        )
        self.field = types.SimpleNamespace(
            reload=lambda: None,
            table_manager=types.SimpleNamespace(
                updateSections=lambda *a, **k: None
            ),
        )


def _patch_optimize_bc(monkeypatch, *, accept_warning, dialog_confirmed=True):
    """Neutralise optimizeBC's three collaborators and record the real work."""
    from PyReconstruct.modules.gui.main import main_window as mw

    calls = []
    monkeypatch.setattr(
        mw.QuickDialog, "get",
        staticmethod(
            lambda *a, **k: ([128, 60.0, [(None, True)]], dialog_confirmed)
        ),
    )
    monkeypatch.setattr(mw, "noUndoWarning", lambda *a, **k: accept_warning)
    monkeypatch.setattr(
        mw, "optimizeSeriesBC",
        lambda *a, **k: calls.append(a),
    )
    return mw, calls


def test_optimize_bc_runs_when_the_warning_is_accepted(monkeypatch):
    mw, calls = _patch_optimize_bc(monkeypatch, accept_warning=True)
    stub = _OptimizeBCStub([1, 2, 3])

    mw.MainWindow.optimizeBC(stub, [1, 2])

    assert len(calls) == 1


def test_optimize_bc_is_aborted_when_the_warning_is_declined(monkeypatch):
    """Declining must stop it before any section is rewritten.

    Brightness and contrast are written straight onto the section and saved,
    with no series_states anywhere in optimizeSeriesBC, so there is nothing to
    undo afterwards. The warning is the only thing standing in front of it.
    """
    mw, calls = _patch_optimize_bc(monkeypatch, accept_warning=False)
    stub = _OptimizeBCStub([1, 2, 3])

    mw.MainWindow.optimizeBC(stub, [1, 2])

    assert calls == []


# ---------------------------------------------------------------------------
# 4. the wishlist's three object edits do record undo
# ---------------------------------------------------------------------------

def _series_and_states(tmp_path):
    if not FIXTURE.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    destination = tmp_path / "shapes1.jser"
    shutil.copyfile(FIXTURE, destination)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    series = Series.openJser(str(destination))
    data = SeriesData(series)
    data.refresh()
    series.data = data
    return series, SeriesStates(series)


def _recorded_sections(states, series):
    return [n for n in series.sections if states[n].undo_states]


def _first_object(series):
    names = list(series.data["objects"].keys())
    assert names, "fixture had no objects"
    return names[0]


def test_editing_object_attributes_records_a_series_undo_state(tmp_path):
    """Name and color, the wishlist's first named case.

    `editObjectAttributes` passes series_states into `enumerateSections`, whose
    `SeriesIterator` calls `addState()` up front and `addState`/`addSectionUndo`
    per modified section. So Ctrl+Z restores the prior name and color.
    """
    series, states = _series_and_states(tmp_path)
    obj = _first_object(series)

    series.editObjectAttributes(
        [obj], color=(1, 2, 3), series_states=states, log_event=False
    )

    assert len(states.undos) == 1
    assert _recorded_sections(states, series), "no section state was recorded"
    series.close()


def test_editing_object_radius_records_a_series_undo_state(tmp_path):
    """Stamp radius, the wishlist's second named case."""
    series, states = _series_and_states(tmp_path)
    obj = _first_object(series)

    series.editObjectRadius([obj], 0.5, states)

    assert len(states.undos) == 1
    assert _recorded_sections(states, series), "no section state was recorded"
    series.close()


def test_editing_object_shape_records_a_series_undo_state(tmp_path):
    """Stamp shape, the other half of the wishlist's second case."""
    series, states = _series_and_states(tmp_path)
    obj = _first_object(series)
    square = [(-1, -1), (1, -1), (1, 1), (-1, 1)]

    series.editObjectShape([obj], square, states)

    assert len(states.undos) == 1
    assert _recorded_sections(states, series), "no section state was recorded"
    series.close()


# ---------------------------------------------------------------------------
# 5. the manual
# ---------------------------------------------------------------------------

FALSE_MANUAL_CLAIMS = (
    # Undo/Redo reach the lists: MainWindow.undo dispatches to
    # series_states.undoState() for a series-wide state.
    "will NOT undo any action made through the object or section list",
    "will NOT redo any action made through the object or section list",
)


def test_manual_does_not_claim_undo_stops_at_the_field():
    text = MANUAL.read_text(encoding="utf-8")
    for claim in FALSE_MANUAL_CLAIMS:
        assert claim not in text, f"manual still says: {claim}"


def test_manual_says_attribute_and_radius_edits_are_undoable():
    """The two sections the wishlist named must say the opposite of before."""
    text = MANUAL.read_text(encoding="utf-8")
    for heading in ("### Edit Attributes", "### Edit Radius"):
        start = text.index(heading)
        end = text.index("\n### ", start + len(heading))
        body = text[start:end]
        assert "cannot be undone" not in body, f"{heading} still says it cannot"
        assert "can be undone with Ctrl+Z" in body, f"{heading} says nothing"


def test_manual_still_warns_that_deleting_a_section_is_irreversible():
    """The true warning stays. Section.deleteSections os.remove()s the file."""
    text = MANUAL.read_text(encoding="utf-8")
    assert "This action CANNOT be undone with Ctrl+Z or Edit>Undo." in text


def test_user_guide_names_the_actions_that_are_not_undoable():
    """The docs-site page listed them as an unspecified "some", which is what
    let the manual's stale claims go unnoticed. Name them instead."""
    guide = (REPO_ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    assert "Some edits\nmade through the lists are noted there as not undoable." \
        not in guide
    for action in ("deleting", "reordering"):
        assert action in guide

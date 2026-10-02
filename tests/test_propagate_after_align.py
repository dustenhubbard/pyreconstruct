"""Starting propagation recording picks up an alignment already made.

Before, "Start propagation recording" had to come before the alignment: a
shift made first was never recorded, so there was nothing to propagate and
the alignment had to be done again. Now every transform change made on the
current section since the last transform change on another section is
included when recording starts. Recording, an undo or redo that moves a
section, and anything that reloads the sections start it over.
"""

import types

import pytest

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.main import field_widget_4_data as fw

pytestmark = pytest.mark.gui


@pytest.fixture
def field(main_window, monkeypatch):
    monkeypatch.setattr(
        fw, "getProgbar",
        lambda *a, **k: types.SimpleNamespace(
            setValue=lambda v: None, close=lambda: None
        ),
    )
    field = main_window.field
    # the fixture series ships with its sections locked
    for n in field.series.sections:
        section = field.series.loadSection(n)
        section.align_locked = False
        section.save()
    field.reload()
    return field


def _others(field):
    return [n for n in sorted(field.series.sections) if n != field.section.n]


def test_correlation_alignment_made_first_propagates(field, monkeypatch):
    start = field.section.n
    other = _others(field)[0]
    field.changeSection(other)
    field.changeSection(start)  # the other section is now the B section
    later = [n for n in sorted(field.series.sections) if n > start]
    assert later, "the fixture series needs a section after the current one"
    before_later = {n: field.series.loadSection(n).tform.copy() for n in later}
    before = field.section.tform.copy()

    monkeypatch.setattr(fw, "correlate", lambda a, b: (12, -8))
    field.corrAlign()
    aligned = field.section.tform.copy()
    assert not aligned.equals(before), "the alignment should move the section"

    field.setPropagationMode(True)
    delta = aligned * before.inverted()
    assert field.stored_tform.equals(delta)

    field.propagateTo(to_end=True)

    assert field.section.tform.equals(aligned), "the current section moved twice"
    for n in later:
        got = field.series.loadSection(n).tform
        assert got.equals(delta * before_later[n]), f"section {n} was not propagated"


def test_every_change_on_the_section_is_included(field):
    before = field.section.tform.copy()
    field.translateTform(3, 4)
    field.translateTform(1, -2)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(field.section.tform * before.inverted())
    assert field.stored_tform.equals(Transform([1, 0, 4, 0, 1, 2]))


def test_checking_against_another_section_keeps_the_change(field):
    start = field.section.n
    field.translateTform(3, 4)
    field.changeSection(_others(field)[0])
    field.changeSection(start)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform([1, 0, 3, 0, 1, 4]))


def test_a_change_made_elsewhere_is_not_included(field):
    start = field.section.n
    field.translateTform(3, 4)
    field.changeSection(_others(field)[0])
    field.translateTform(5, 5)
    field.changeSection(start)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_an_undone_change_is_not_included(field):
    field.translateTform(3, 4)
    field.undoState()

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_a_recorded_change_is_not_included_again(field):
    field.translateTform(3, 4)
    field.setPropagationMode(True)
    field.translateTform(1, 1)
    field.setPropagationMode(False)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def _import_transforms(field, tmp_path):
    fp = tmp_path / "imported.txt"
    fp.write_text("".join(
        f"{n} 1 0 100 0 1 50\n" for n in field.series.sections
    ))
    field.mainwindow.importTransforms(str(fp))


def test_imported_transforms_are_not_included(field, tmp_path, monkeypatch):
    # an import reloads the field, as a series undo and inserting or
    # reordering sections do
    monkeypatch.setattr("PyReconstruct.modules.gui.main.main_window.notify", lambda *a, **k: None)
    field.translateTform(3, 4)
    _import_transforms(field, tmp_path)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_a_section_inserted_in_its_place_is_not_included(field):
    start = field.section.n
    field.translateTform(3, 4)
    field.mainwindow.saveAllData()
    field.series.insertSection(start, "no-image", field.section.mag, field.section.thickness)
    field.clearStates()
    field.reload()
    field.changeSection(start)  # the new section now has the old number

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_undoing_past_the_first_change_here_is_not_included(field):
    start = field.section.n
    field.translateTform(3, 4)
    field.changeSection(_others(field)[0])
    field.translateTform(5, 5)
    field.changeSection(start)
    field.translateTform(1, 1)
    field.undoState()
    field.undoState()

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_a_redone_change_is_not_included(field):
    # a redo moves the section like an undo does, so recording starts over
    field.translateTform(3, 4)
    moved = field.section.tform.copy()
    field.undoState()
    field.undoState(redo=True)
    assert field.section.tform.equals(moved), "the redo should move the section back"

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform.identity())


def test_a_change_after_a_redo_is_included_alone(field):
    field.translateTform(3, 4)
    field.undoState()
    field.undoState(redo=True)
    field.translateTform(1, -2)

    field.setPropagationMode(True)

    assert field.stored_tform.equals(Transform([1, 0, 1, 0, 1, -2]))


def _set_tforms(field, tforms):
    for n, t in tforms.items():
        section = field.series.loadSection(n)
        section.tform = t
        section.save()
    field.reload()


def test_affine_changes_that_do_not_commute_propagate_in_order(field):
    start = field.section.n
    later = [n for n in sorted(field.series.sections) if n > start]
    assert later, "the fixture series needs a section after the current one"
    # every section starts somewhere different, so the order matters
    base = Transform([1.1, 0.2, 5, -0.1, 0.9, -3])
    _set_tforms(field, {start: base, **{
        n: Transform([1, 0.05 * i, 2 * i, 0, 1.2, -i]) for i, n in enumerate(later, 1)
    }})
    before_later = {n: field.series.loadSection(n).tform.copy() for n in later}

    rotate = Transform([0, -1, 0, 1, 0, 0])
    shear = Transform([1, 0.5, 0, 0, 1, 0])
    assert not (rotate * shear).equals(shear * rotate), "pick transforms that do not commute"
    field.changeTform(field.section.tform * rotate)
    field.changeTform(field.section.tform * shear)
    aligned = field.section.tform.copy()

    field.setPropagationMode(True)
    delta = aligned * base.inverted()
    assert field.stored_tform.equals(delta)
    assert not field.stored_tform.equals(base.inverted() * aligned)

    field.propagateTo(to_end=True)

    assert field.section.tform.equals(aligned), "the current section moved twice"
    for n in later:
        got = field.series.loadSection(n).tform
        assert got.equals(delta * before_later[n]), f"section {n} was not propagated"
        assert not got.equals(before_later[n] * delta), f"section {n} took the wrong order"

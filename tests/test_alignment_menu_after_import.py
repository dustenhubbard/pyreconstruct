"""The alignment submenu after an alignment import, through a live MainWindow.

`Alignments > Import alignments` has two entries, `From .txt file...` and
`From SWiFT project...`. Both create an alignment and make it current
(`series.alignment = new_alignment_name` in the two backend functions), and
neither used to rebuild the menus afterwards.

Why that is not only a missing entry. `MainWindow.changeAlignment` resolves
both the new and the *current* alignment to an action with a bare
`getattr(self, f"{name}_alignment_act")`, and those attributes exist only
because `createContextMenus()` created them from `series.alignments`. So after
an import, `series.alignment` names an alignment with no action, and the next
alignment switch by any route raises `AttributeError` on the current name. The
exception escapes into `customExcepthook`, which raises a modal error report,
so the user gets an error dialog and no alignment change. Both switch routes
are covered below.

These drive a real `MainWindow` (see the `main_window` fixture in conftest),
because the defect is entirely in the widget state: the series data is correct
throughout.
"""

import sys

import pytest


def _write_tforms_file(series, path):
    """A well-formed transforms file: identity for every section in the series.

    The format the importer wants is seven whitespace-separated numbers per
    line, `<section number> a1 a2 a3 b1 b2 b3`.
    """
    with open(path, "w") as f:
        for snum in sorted(series.sections):
            f.write(f"{snum} 1 0 0 0 1 0\n")
    return str(path)


def _write_swift_project(series, path):
    """A minimal SWiFT project file in the newer `stack`/`levels` format.

    `make_pyr_transforms` reads `stack[i]["levels"]["s<scale>"]` for
    `swim_settings.img_size` and `alt_cafm`, and `importSwiftTransforms`
    requires one entry per section. `MainWindow.importSwiftTransforms` reads
    the available scales from `level_data`.
    """
    import json

    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    level = {"swim_settings": {"img_size": [100, 100]}, "alt_cafm": identity}
    project = {
        "level_data": {"s1": {}},
        "stack": [{"levels": {"s1": level}} for _ in series.sections],
    }
    with open(path, "w") as f:
        json.dump(project, f)
    return str(path)


def _alignment_submenu_items(window):
    """The entries of the field context menu's "Series alignment" submenu.

    Found via `findChildren` deliberately. Reaching the submenu through
    `QAction.menu()` instead hands the `QMenu` to Python's ownership and the
    C++ object is destroyed when the temporary wrapper is collected, which
    shows up later as `RuntimeError: Internal C++ object (QMenu) already
    deleted` from an unrelated `checkActions()` call.
    """
    from PySide6.QtWidgets import QMenu

    for menu in window.field_menu.findChildren(QMenu):
        if menu.title() == "Series alignment":
            return [action.text() for action in menu.actions()]
    raise AssertionError("no 'Series alignment' submenu in the field menu")


def _alignment_act_names(window):
    return {name for name in dir(window) if name.endswith("_alignment_act")}


@pytest.fixture
def recorded_excepthook(monkeypatch):
    """Record what `customExcepthook` would report, without its modal dialog.

    `MainWindow.__init__` installs `customExcepthook` process-wide, and it ends
    in `show_error_report`, a modal that offscreen Qt never dismisses. A test
    that triggers a real `QAction` whose slot raises would otherwise hang
    rather than fail (measured: 120s and still going). Recording the exception
    keeps the failure mode a readable assertion.
    """
    seen = []
    monkeypatch.setattr(
        sys, "excepthook", lambda exctype, value, tb: seen.append(
            (exctype.__name__, str(value))
        )
    )
    return seen


@pytest.mark.gui
def test_txt_import_adds_the_alignment_to_the_submenu(main_window, tmp_path):
    """The imported alignment appears in the submenu that is meant to list it."""
    window = main_window
    before = _alignment_submenu_items(window)
    assert before == sorted(window.series.alignments)

    tforms_fp = _write_tforms_file(window.series, tmp_path / "myalign.txt")
    window.importTransforms(tforms_fp)

    imported = window.series.alignment
    assert imported not in before, "the fixture series already had this name"
    assert imported in window.series.alignments
    assert imported in _alignment_submenu_items(window)
    assert f"{imported}_alignment_act" in _alignment_act_names(window)


@pytest.mark.gui
def test_txt_import_checks_the_alignment_it_made_current(main_window, tmp_path):
    """The submenu's checkmark follows series.alignment, not the old value."""
    window = main_window
    was_current = window.series.alignment
    assert getattr(window, f"{was_current}_alignment_act").isChecked()

    tforms_fp = _write_tforms_file(window.series, tmp_path / "myalign.txt")
    window.importTransforms(tforms_fp)

    imported = window.series.alignment
    assert getattr(window, f"{imported}_alignment_act").isChecked()
    assert not getattr(window, f"{was_current}_alignment_act").isChecked()


@pytest.mark.gui
def test_switching_alignment_from_the_submenu_after_a_txt_import(
    main_window, tmp_path, recorded_excepthook
):
    """Route one: field right-click > Series alignment > default."""
    window = main_window
    tforms_fp = _write_tforms_file(window.series, tmp_path / "myalign.txt")
    window.importTransforms(tforms_fp)
    assert window.series.alignment != "default"

    window.default_alignment_act.trigger()

    assert recorded_excepthook == []
    assert window.series.alignment == "default"


@pytest.mark.gui
def test_edit_alignments_dialog_after_a_txt_import(
    main_window, tmp_path, monkeypatch
):
    """Route two: Alignments > Edit alignments..., selecting an existing name.

    The dialog itself was never the stale part: it lists
    `field.section.tforms.keys()`, which does include the imported alignment.
    What failed was `modifyAlignments` handing the choice to
    `changeAlignment`, which then could not find an action for the current one.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    window = main_window
    tforms_fp = _write_tforms_file(window.series, tmp_path / "myalign.txt")
    window.importTransforms(tforms_fp)
    imported = window.series.alignment

    offered = []

    class SelectDefault:
        def __init__(self, parent, alignments, current):
            offered.extend(alignments)

        def exec(self):
            # (alignment to switch to, rename dict); no renames
            return ("default", None), True

    monkeypatch.setattr(mw, "AlignmentDialog", SelectDefault)

    window.modifyAlignments()

    assert imported in offered
    assert window.series.alignment == "default"


@pytest.mark.gui
def test_swift_import_adds_the_alignment_to_the_submenu(
    main_window, tmp_path, main_window_dialogs, recorded_excepthook
):
    """The SWiFT entry is the same defect at the sibling menu item."""
    window = main_window
    before = _alignment_submenu_items(window)

    swift_fp = _write_swift_project(window.series, tmp_path / "swiftproj.json")
    # scale combo -> "1"; "Includes cal grid" unchecked
    main_window_dialogs.responses.append(
        (["1", [("Includes cal grid", False)]], True)
    )
    window.importSwiftTransforms(swift_fp)

    imported = window.series.alignment
    assert imported not in before
    assert imported in _alignment_submenu_items(window)

    window.default_alignment_act.trigger()
    assert recorded_excepthook == []
    assert window.series.alignment == "default"


@pytest.mark.gui
def test_a_malformed_transforms_file_does_not_rebuild_the_menus(
    main_window, tmp_path, monkeypatch
):
    """The rebuild is conditional on the names actually changing.

    `createContextMenus()` recreates on the order of 200 actions, and the
    importer bails out on a bad file without touching any alignment (it prints
    "Incorrect transform file format" and returns). Guards the condition, not
    just the happy path.
    """
    window = main_window
    rebuilds = []
    real = window.createContextMenus
    monkeypatch.setattr(
        window, "createContextMenus",
        lambda: (rebuilds.append(1), real())[1]
    )

    bad_fp = tmp_path / "bad.txt"
    bad_fp.write_text("not a transform\n")
    before = set(window.series.alignments)

    window.importTransforms(str(bad_fp))

    assert set(window.series.alignments) == before
    assert rebuilds == []

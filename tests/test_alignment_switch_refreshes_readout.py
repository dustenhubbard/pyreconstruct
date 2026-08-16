"""Switching alignment leaves the status readout correct, from every route in.

The status bar's permanent readout names the current alignment
(``FieldWidget.updateStatusBar`` composes
``"Section: 52  |  Alignment: default  |  ..."``). Nothing in
``MainWindow.changeAlignment`` used to refresh it. ``field.changeAlignment``
reassigns ``series.alignment``, reloads and recreates the tables, but it does
not repaint synchronously, so the bar named the *old* alignment on return.
Measured on the fixture series before the fix, driving the real context-menu
action:

    BEFORE: 'Section: 52  |  Alignment: default  |  ...'
    series.alignment now: LOCAL_d03
    AFTER : 'Section: 52  |  Alignment: default  |  ...'

**What this is not.** It is not a bug a user of the app can see, and these
tests are written knowing that rather than around it. ``reload()`` ends in
``generateView() -> self.update()``, so the next event-loop turn paints and
``paintEvent -> paintText`` calls ``updateStatusBar`` itself. Measured on a
*shown* window with the fix reverted, the staleness lasts exactly until the
first ``processEvents()``:

    IMMEDIATELY AFTER:          'Alignment: default'
    after processEvents x1:     'Alignment: LOCAL_d03'

So what is pinned here is a *postcondition*, not a visible defect: when
``changeAlignment`` returns, the bar agrees with ``series.alignment``, with no
scheduled repaint in the trust chain. That is the postcondition
``MainWindow.changeSection`` already has (it calls ``field.updateStatusBar()``
right after ``field.changeSection()``), and having it here is what lets a new
route -- a clickable status bar, say -- switch alignment without repeating the
refresh. The tests deliberately do **not** pump the event loop, because pumping
it would make every assertion below pass with or without the fix.

The postcondition was missing for every caller, not one, which is why the
refresh belongs in the shared method rather than at a call site. Two routes
reach ``MainWindow.changeAlignment`` today and both lacked it:

* the field context menu's "Series alignment" submenu, wired in
  ``context_menu_list.py`` as ``getAlignmentsMenu(self.series,
  self.changeAlignment)``; and
* ``Alignments > Edit alignments...``, whose ``modifyAlignments`` hands the
  dialog's choice to ``changeAlignment(..., overwrite=True)``.

Both are driven here through their real entry points -- a ``QAction.trigger()``
for the first, the monkeypatched dialog for the second -- rather than by calling
``changeAlignment`` directly, so a fix that only patched one caller would fail.
``test_the_shared_method_is_what_refreshes`` then pins the placement itself: it
asserts the refresh happens for *any* caller, which is the property that lets a
future route (a clickable status bar, say) switch alignment without repeating
the refresh.

The no-op path is pinned too. ``createContextMenus`` ends with
``self.changeAlignment(self.series.alignment)`` purely to tick the right
checkbox -- it must not reload or recompose anything, so the refresh sits
*inside* the ``if overwrite or new != current`` guard beside the reload it
follows, not after it.
"""

import pytest

from PySide6.QtWidgets import QMenu

pytestmark = pytest.mark.gui

SUBMENU_TITLE = "Series alignment"


def readout(window):
    """What the status bar's permanent readout currently shows.

    Asks which readout widget is mounted rather than naming one, because two
    shapes are in flight. On ``main`` the permanent widget is the flat
    ``status_label`` (a ``QLabel``); the clickable-status-bar change replaces
    it with ``status_readout``, a ``FieldStatusReadout`` whose ``text()``
    returns the same ``"  |  "``-joined string, so everything parsed out of it
    below reads identically either way. ``FieldWidget.updateStatusBar`` is
    already defensive about exactly this -- it reaches the permanent widget
    through ``getattr(self.mainwindow, ..., None)`` -- and hard-coding one
    name here is what would make these tests pass alone and fail on a tree
    carrying both changes.

    Raises when neither exists rather than returning something empty: a
    readout helper that quietly reported nothing would leave every assertion
    below green while pinning nothing at all.
    """
    for attr in ("status_label", "status_readout"):
        widget = getattr(window, attr, None)
        if widget is not None:
            return widget.text()
    raise AssertionError(
        "main window carries neither 'status_label' nor 'status_readout'; "
        "the permanent status-bar readout has been renamed again"
    )


def alignment_named_in_readout(window):
    """The alignment the readout claims, parsed out of the joined line."""
    for part in readout(window).split("  |  "):
        if part.startswith("Alignment: "):
            return part[len("Alignment: "):]
    raise AssertionError(f"no alignment segment in readout {readout(window)!r}")


def submenu_actions(window):
    """The "Series alignment" submenu's actions, found by title.

    By title rather than by attribute because ``getAlignmentsMenu`` and
    ``return_alignments_menu`` both claim the ``alignmentsmenu`` attribute, so
    the attribute is whichever was built last.
    """
    for menu in window.field_menu.findChildren(QMenu):
        if menu.title() == SUBMENU_TITLE:
            return {action.text(): action for action in menu.actions()}
    raise AssertionError(f"no {SUBMENU_TITLE!r} submenu in the field menu")


def another_alignment(window):
    """A name in the current section's transforms that is not the current one."""
    current = window.series.alignment
    for name in sorted(window.field.section.tforms.keys()):
        if name != current:
            return name
    raise AssertionError("fixture series carries only one alignment")


def test_the_context_menu_route_refreshes_the_readout(main_window):
    """Route one: right-click > Series alignment > <name>.

    Triggered through the submenu's own ``QAction`` so the assertion covers the
    wiring in ``context_menu_list.py`` as well as the switch itself.
    """
    window = main_window
    window.field.updateStatusBar()
    before = window.series.alignment
    assert alignment_named_in_readout(window) == before

    target = another_alignment(window)
    submenu_actions(window)[target].trigger()

    assert window.series.alignment == target
    assert alignment_named_in_readout(window) == target


def test_the_edit_alignments_dialog_route_refreshes_the_readout(
    main_window, monkeypatch
):
    """Route two: Alignments > Edit alignments..., selecting another name.

    ``modifyAlignments`` calls ``changeAlignment(..., overwrite=True)``, so this
    also covers the overwrite branch that route one does not reach.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    window = main_window
    window.field.updateStatusBar()
    target = another_alignment(window)

    class SelectTarget:
        def __init__(self, parent, alignments, current):
            pass

        def exec(self):
            # (alignment to switch to, rename dict); no renames
            return (target, None), True

    monkeypatch.setattr(mw, "AlignmentDialog", SelectTarget)

    window.modifyAlignments()

    assert window.series.alignment == target
    assert alignment_named_in_readout(window) == target


def test_the_shared_method_is_what_refreshes(main_window):
    """The placement, not one route's behavior.

    Asserted on ``MainWindow.changeAlignment`` with no menu and no dialog in the
    picture, because that is the contract a new caller relies on: switch through
    this method and the readout is correct when it returns. A fix that lived in
    the two callers above would pass both of those tests and fail this one --
    measured, not assumed: adding the refresh at both call sites and leaving the
    shared method untouched fails this test alone, 1 of 5.
    """
    window = main_window
    window.field.updateStatusBar()
    target = another_alignment(window)

    window.changeAlignment(target)

    assert alignment_named_in_readout(window) == target


def test_switching_to_the_current_alignment_recomposes_nothing(
    main_window, monkeypatch
):
    """The no-op path stays a no-op, which is why the refresh sits in the guard.

    ``createContextMenus`` ends with ``changeAlignment(series.alignment)`` purely
    to tick the right checkbox, and it runs on every menu rebuild -- an alignment
    import, a series undo that changed the names, ~200 actions at a time. That
    call must not reload the field and must not ask it to rebuild the readout.

    Counting ``updateStatusBar`` calls rather than ``setText`` writes, and this
    is the whole point of the test: ``updateStatusBar`` writes only when the
    composed string differs from what is displayed, so an unconditional refresh
    at the end of ``changeAlignment`` would produce no write here and a
    write-counting assertion would pass on it. It would still recompose the line
    on every menu rebuild -- ``pixmapPointToField`` and the join -- for a switch
    that did nothing. Measured: with the refresh moved outside the guard this
    test fails and the other four still pass, so this is the only one holding
    the placement.
    """
    window = main_window
    window.field.updateStatusBar()
    current = window.series.alignment

    calls = []
    monkeypatch.setattr(
        type(window.field),
        "updateStatusBar",
        lambda self, trace=None: calls.append(trace),
    )

    window.changeAlignment(current)

    assert calls == []
    assert window.series.alignment == current
    assert getattr(window, f"{current}_alignment_act").isChecked()


def test_a_stale_submenu_entry_still_raises_rather_than_being_swallowed(
    main_window
):
    """The refresh must not turn the stale-entry failure into a silent one.

    ``test_alignment_submenu_after_undo`` pins that selecting a submenu entry the
    sections no longer carry raises ``KeyError`` out of ``field.reload()``. The
    new ``updateStatusBar()`` call sits *after* that reload, so the exception
    still propagates -- but a later refactor that moved the refresh ahead of the
    switch, or wrapped it, could mask it. Pinned here beside the refresh it
    guards rather than only in the other file.
    """
    window = main_window
    valid = window.series.alignment

    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict["stale_probe"] = valid
    window.series.modifyAlignments(alignment_dict, window.field.series_states)
    window.createContextMenus()

    alignment_dict = {
        a: a for a in window.series.alignments if a != "stale_probe"
    }
    window.series.modifyAlignments(alignment_dict, window.field.series_states)

    assert "stale_probe" not in window.field.section.tforms

    with pytest.raises(KeyError):
        window.changeAlignment("stale_probe")

    # leave the field renderable: the failed switch had already assigned the
    # name, and every later paint would raise on it
    window.series.alignment = valid
    window.field.reload()

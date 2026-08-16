"""Regression guards for the review feedback on "Copy to sections" (PR #103).

Two behavioral requests came out of that review, and each gets a guard here
because neither was pinned by a test before:

1. **"copy" greys out when nothing is selected -- do the same for
   copy-to-sections.** The enabled state of the clipboard actions is not managed
   per action: ``MainWindow.createContextMenus`` collects them into
   ``self.trace_actions`` and ``MainWindow.checkActions`` enables/disables that
   whole list in one pass. So "behaves the same as copy" is precisely
   "is a member of the same list as ``copy_act``", and that is what
   ``test_copy_to_sections_greys_out_with_copy`` asserts -- by running the REAL
   ``createContextMenus`` rather than restating the list, so deleting the line
   fails the test.

2. **Give it a shortcut next to Ctrl+C.** ``Ctrl+Shift+C`` was requested, but it
   is not free: it has been ``togglecuration_act``'s default for longer than
   this feature has existed, and ``docs/USER_GUIDE.md`` documents it. The key
   went to ``Ctrl+Alt+C`` instead. Two guards follow from that: the whole
   configurable shortcut set must stay collision-free (the check that would have
   caught the bad assumption in the first place), and ``Ctrl+Shift+C`` must
   still belong to curation.

``MainWindow(...)`` cannot be constructed in the suite (it blocks offscreen), so
the gating test calls the unbound method against a ``QWidget`` stub -- enough for
``QMenu(self)`` and ``populateMenu`` to do their real work.
"""

import pytest

from PyReconstruct.modules.datatypes.default_settings import (
    default_settings as qsettings_defaults,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _main_window_stub(series):
    """A QWidget carrying just the surface ``createContextMenus`` touches.

    It must be a real QWidget (``QMenu(self)`` and ``widget.addAction``), and the
    four clipboard actions must be real QActions because the menu list embeds
    those objects directly rather than building them from tuples.
    """
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QAction
    from test_context_menu_frequency import _FieldStub

    class Stub(QWidget):
        def __getattr__(self, name):
            # changeAlignment / importLabels / mergeLabels / ... -- harmless
            return lambda *a, **k: []

    stub = Stub()
    stub.series = series
    stub.field = _FieldStub(series)
    for name in ("cut_act", "copy_act", "paste_act", "pasteattributes_act"):
        setattr(stub, name, QAction(name))
    return stub


# --------------------------------------------------------------------------- #
# 1. the greyed-out state
# --------------------------------------------------------------------------- #
def test_copy_to_sections_greys_out_with_copy(qapp, real_series):
    """copytosections_act must ride in trace_actions with copy_act.

    checkActions only ever setEnabled()s that list uniformly, so co-membership
    IS the "greys out exactly like copy" behavior. Running the real
    createContextMenus is what makes this a regression test: restating the list
    here would pass even with the line deleted.
    """
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    stub = _main_window_stub(real_series)
    MainWindow.createContextMenus(stub)

    assert stub.copy_act in stub.trace_actions, (
        "copy_act is not gated -- the premise of this test is gone, re-read "
        "createContextMenus"
    )
    assert stub.copytosections_act in stub.trace_actions, (
        '"Copy to sections..." is not in trace_actions, so it stays enabled '
        "with no selection while Copy greys out (PR #103 review)"
    )


def test_gated_trace_actions_all_start_from_the_same_pass(qapp, real_series):
    """A cheap proof that the gating really is one uniform sweep: flipping the
    list off then on leaves copy and copy-to-sections in the same state."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    stub = _main_window_stub(real_series)
    MainWindow.createContextMenus(stub)

    for enabled in (False, True):
        for act in stub.trace_actions:
            act.setEnabled(enabled)
        assert stub.copytosections_act.isEnabled() == stub.copy_act.isEnabled()


# --------------------------------------------------------------------------- #
# 2. the shortcut
# --------------------------------------------------------------------------- #
# Every act_name in qsettings_defaults whose value is a key sequence. The dict
# also holds non-shortcut options, so the shortcut block is identified by the
# "_act" suffix -- the same convention getStaticShortcuts relies on.
def _configurable_shortcuts() -> dict:
    return {
        name: value
        for name, value in qsettings_defaults.items()
        if name.endswith("_act") and isinstance(value, str) and value
    }


def test_copy_to_sections_has_a_configurable_shortcut():
    """The action must own a real, user-configurable default key."""
    assert qsettings_defaults.get("copytosections_act") == "Ctrl+Alt+C"


def test_copy_to_sections_did_not_take_ctrl_shift_c():
    """Ctrl+Shift+C was requested in review but was already spoken for.

    Pinned in both directions so a future "let's just use Ctrl+Shift+C" lands on
    a failing test that names the conflict instead of silently shadowing a
    documented binding.
    """
    assert qsettings_defaults["togglecuration_act"] == "Ctrl+Shift+C"
    assert qsettings_defaults["copytosections_act"] != "Ctrl+Shift+C"


def test_no_two_actions_share_a_default_shortcut():
    """The configurable shortcut set must be collision-free.

    This is the guard that was missing: nothing stopped a new action from being
    handed a key another action already had, and Qt resolves such a clash by
    firing neither (ambiguous shortcut) -- a silent, hard-to-report breakage.
    """
    seen = {}
    collisions = []
    for name, key in sorted(_configurable_shortcuts().items()):
        norm = key.strip().lower()
        if norm in seen:
            collisions.append(f"{key!r}: {seen[norm]} and {name}")
        else:
            seen[norm] = name
    assert not collisions, "duplicate default shortcuts: " + "; ".join(collisions)


def test_trace_list_menu_still_binds_no_shortcut_for_copy_to_sections(qapp, real_series):
    """Keys are connected through the FIELD only. The trace-list variant of the
    menu carries the same act_name, and must leave it unbound -- otherwise the
    list menu and the field menu fight over Ctrl+Alt+C."""
    from PyReconstruct.modules.gui.main.context_menu_list import (
        get_context_menu_list_trace,
    )
    from test_context_menu_frequency import _Anything, _series

    rows = get_context_menu_list_trace(
        _Anything(series=_series()),
        is_in_field=False,
        list_ops=[],
    )
    kbds = {r[0]: r[2] for r in rows if isinstance(r, tuple)}
    assert kbds["copytosections_act"] == ""


# --------------------------------------------------------------------------- #
# 3. the reviewed placeholder text
# --------------------------------------------------------------------------- #
class _SeriesStub:
    """Only what CopyToSectionsDialog reads off a Series."""

    def __init__(self, section_numbers):
        self.sections = {n: object() for n in section_numbers}


def _dialog(qapp, section_numbers):
    """Construct the dialog (never exec it -- a modal never returns offscreen)."""
    from PyReconstruct.modules.gui.dialog.copy_to_sections import (
        CopyToSectionsDialog,
    )
    return CopyToSectionsDialog(None, _SeriesStub(section_numbers))


def test_placeholder_only_suggests_sections_that_exist(qapp):
    """The reviewed placeholder samples real sections, so a gappy series is never
    shown an example it would then reject. Sampling range(smin, smax + 1), as
    first suggested, would offer the missing middle."""
    import re

    existing = [0, 1, 2, 3, 96, 97, 98, 99]
    dlg = _dialog(qapp, existing)
    try:
        placeholder = dlg.spec_input.placeholderText()
        # the second example is the comma-joined sample; the first is smin-smax
        sample = placeholder.split(" or ")[1]
        picked = [int(tok) for tok in re.findall(r"\d+", sample)]
        assert picked, placeholder
        assert set(picked) <= set(existing), (
            f"placeholder {placeholder!r} names sections that do not exist: "
            f"{sorted(set(picked) - set(existing))}"
        )
        assert picked == sorted(picked), f"sample not sorted: {placeholder!r}"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_placeholder_survives_a_series_smaller_than_the_sample(qapp, count):
    """random.sample raises ValueError when the population is under k, so a one-
    or two-section series would have crashed the dialog on open with the
    unclamped k=3 from the review suggestion."""
    dlg = _dialog(qapp, range(count))
    try:
        assert dlg.spec_input.placeholderText()
    finally:
        dlg.deleteLater()

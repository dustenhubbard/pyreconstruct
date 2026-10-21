"""The User Guide's tool and shortcut tables match PyReconstruct.

``scripts/docs_tables.py`` writes them from the source (the shipped defaults,
the rows of Help > Shortcuts list, the tool palette). When the committed guide
differs, the fix is one command:

    python3 scripts/docs_tables.py --write

The generator reads source files, without Qt. The gui tests at the end build a
real MainWindow and compare the generated tables with its live objects: the
palette buttons, the actions their keys trigger, the rows of the shortcuts
dialog, and the shortcut of each named action. A table row the window lacks,
or a live binding the table lacks, fails.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from PyReconstruct.modules.constants.roi_mode import ACTION_KEYS, ENV_SWITCH
from PyReconstruct.modules.datatypes.default_settings import default_settings

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "docs_tables.py"

_spec = importlib.util.spec_from_file_location("docs_tables", SCRIPT)
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)


@pytest.fixture(autouse=True)
def roi_mode_unset(monkeypatch):
    """Before main_window builds: the live side must show what users see."""
    monkeypatch.delenv(ENV_SWITCH, raising=False)


def _guide() -> str:
    return (ROOT / dt.GUIDE).read_text(encoding="utf-8")


def _all_rendered() -> str:
    return "\n".join(render() for render in dt.BLOCKS.values())


def test_guide_tables_are_fresh():
    stale = dt.stale_parts(_guide())
    assert not stale, (
        f"{dt.GUIDE} does not match the source ({', '.join(stale)}). "
        f"Run: {dt.FIX_COMMAND}"
    )


def test_a_stale_row_is_caught():
    """Guards the check itself: a wrong key in the committed table is stale."""
    text = _guide()
    row = "| `Shift+M` | Merge selected traces |"
    assert row in text
    assert dt.stale_parts(text.replace(row, "| `Ctrl+M` | Merge selected traces |")) == [
        "shortcuts"
    ]


def test_a_stale_tool_heading_is_caught():
    text = _guide()
    assert "### Knife (`K`)" in text
    assert dt.stale_parts(text.replace("### Knife (`K`)", "### Knife (`J`)")) == [
        "tool headings"
    ]


def test_each_default_key_is_listed():
    """A default with a key and no row in Help > Shortcuts list is a gap in both."""
    listed = {
        name for name in (
            item[0] for item in dt.help_rows() if isinstance(item, tuple)
        )
    }
    missing = [
        name for name, key in default_settings.items()
        if name.endswith("_act") and key and name not in ACTION_KEYS
        and name not in listed
    ]
    assert not missing, f"no Help > Shortcuts list row for: {missing}"


def test_held_roi_mode_never_appears(monkeypatch):
    plain = _all_rendered()
    assert "roi" not in plain.lower()
    for name in ACTION_KEYS:
        if default_settings[name]:
            assert f"`{default_settings[name]}` |" not in plain
    monkeypatch.setenv(ENV_SWITCH, "1")
    assert _all_rendered() == plain, "the guide must not depend on PYRECON_ROI_MODE"


@pytest.mark.parametrize("stored, shown", [
    ("Shift+M", "`Shift+M`"),
    ("P", "`P`"),
    ("Ctrl+Shift+V", "`Cmd+Shift+V` (`Ctrl+Shift+V` on Windows/Linux)"),
    ("Ctrl+Alt+R", "`Cmd+Option+R` (`Ctrl+Alt+R` on Windows/Linux)"),
    ("Ctrl+\\", "`Cmd+\\` (`Ctrl+\\` on Windows/Linux)"),
])
def test_key_text(stored, shown):
    assert dt.key_text(stored) == shown


def test_macos_names_match_the_app(monkeypatch):
    """The generator's macOS names are the ones the shortcuts dialog shows."""
    from PyReconstruct.modules.gui import modifiers

    # Meta is left out: the dialog drops it on macOS, where it cannot be held
    monkeypatch.setattr(modifiers.sys, "platform", "darwin")
    assert modifiers.display_label("ctrl+alt") == f"{dt.MAC_NAMES['Ctrl']}+{dt.MAC_NAMES['Alt']}"


def _md_tables(text: str) -> list:
    """(heading, [row cells]) per Markdown table, header and rule rows left out."""
    tables, heading, rows = [], None, None
    for line in text.splitlines():
        if line.startswith("### "):
            heading = line[4:]
        elif line.startswith("|"):
            cells = [
                c.strip().replace("\\|", "|")
                for c in re.split(r"(?<!\\)\|", line)[1:-1]
            ]
            if rows is None:
                rows = []
                tables.append((heading, rows))
            elif not set("".join(cells)) <= set("-"):
                rows.append(tuple(cells))
        else:
            rows = None
    return tables


def _live_actions(window) -> dict:
    """Name -> QAction for each ``*_act`` attribute of the window."""
    from PySide6.QtGui import QAction

    return {
        name: getattr(window, name)
        for name in dir(window)
        if name.endswith("_act") and isinstance(getattr(window, name, None), QAction)
    }


def _live_tool_rows(window) -> list:
    """(tool, key cell) per palette button, top to bottom, from the window.

    Each keyed action with no text (it sits in no menu, so its key is its only
    way in) is triggered once with the palette's switch recorded, which gives
    the key that picks each tool.
    """
    palette = window.mouse_palette
    picked = []
    keys = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(palette, "activateModeButton", picked.append)
        for act in _live_actions(window).values():
            if act.text() or act.shortcut().isEmpty():
                continue
            picked.clear()
            act.trigger()
            for tool in picked:
                keys[tool] = act.shortcut().toString()
    order = sorted(palette.mode_buttons.items(), key=lambda kv: kv[1][2])
    return [(name, dt.key_text(keys.get(name, ""))) for name, _ in order]


def _rendered_tool_rows(root=dt.ROOT) -> list:
    (table,) = _md_tables(dt.render_tools(root))
    return table[1]


def _live_shortcut_tables(window) -> list:
    """(heading, [(key cell, action)]) as the live shortcuts dialog lays them out."""
    from PySide6.QtWidgets import QKeySequenceEdit, QLabel, QScrollArea

    from PyReconstruct.modules.gui.dialog import ShortcutsDialog
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    dialog = ShortcutsDialog(window, window.series)
    try:
        grid = dialog.findChild(QScrollArea).widget().layout()
        groups = []
        for row in range(grid.rowCount()):
            first, second = (grid.itemAtPosition(row, col) for col in (0, 1))
            widget = first.widget() if first else None
            if second is None:
                if isinstance(widget, QLabel) and widget.text().strip():
                    groups.append((widget.text().rstrip(":"), []))
                continue
            desc = second.widget().text()
            rows = groups[-1][1]
            if isinstance(widget, QKeySequenceEdit):
                stored = widget.keySequence().toString()
            elif isinstance(widget, ModifierEdit):
                stored = dt._modifier_text(widget.modifierString())
            elif widget.text():
                stored = widget.text()
            else:  # the continuation line of the row above
                key, prev = rows[-1]
                rows[-1] = (key, f"{prev.rstrip('.')}. {desc.rstrip('.')}.")
                continue
            if stored:
                rows.append((dt.key_text(stored), desc))
    finally:
        dialog.deleteLater()
    return [(heading, rows) for heading, rows in groups if rows]


## Actions outside the defaults: the dialog shows each as a fixed row
STATIC_ROWS = {
    "delete_act": ("Del", "`Delete/Backspace`"),
    "nextsection_act": ("PgUp", "`Page Up`"),
    "prevsection_act": ("PgDown", "`Page Down`"),
    "shortcutshelp_act": ("?", "`? (Shift+/)`"),
}


@pytest.mark.gui
def test_tool_table_matches_the_live_palette(main_window):
    assert _rendered_tool_rows() == _live_tool_rows(main_window)


@pytest.mark.gui
def test_a_tool_key_the_generator_misses_is_caught(main_window, tmp_path):
    """Guards the check above: Pointer's binding moved out of the list literal
    reads as (none) to the generator, while the window still binds P."""
    for rel in (
        "datatypes/default_settings.py",
        "constants/roi_mode.py",
        "gui/dialog/shortcuts.py",
        "gui/palette/mouse_palette.py",
        "gui/main/main_window.py",
    ):
        dest = tmp_path / dt.PKG / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((dt.ROOT / dt.PKG / rel).read_text(encoding="utf-8"), encoding="utf-8")
    source = tmp_path / dt.PKG / "gui/main/main_window.py"
    text = source.read_text(encoding="utf-8")
    line = '            ("usepointer_act", lambda : self.mouse_palette.activateModeButton("Pointer")),\n'
    end = "        ]\n        # held: B picks ROI mode"
    assert line in text and end in text
    moved = text.replace(line, "").replace(
        end,
        '        ]\n        mode_shortcuts.insert(0, ("usepointer_act", '
        'lambda : self.mouse_palette.activateModeButton("Pointer")))\n'
        "        # held: B picks ROI mode",
    )
    source.write_text(moved, encoding="utf-8")

    stale = _rendered_tool_rows(tmp_path)
    assert ("Pointer", "(none)") in stale
    assert stale != _live_tool_rows(main_window)


@pytest.mark.gui
def test_shortcut_tables_match_the_live_dialog(main_window):
    rendered = [(h, [tuple(r) for r in rows]) for h, rows in _md_tables(dt.render_shortcuts())]
    assert rendered == _live_shortcut_tables(main_window)


@pytest.mark.gui
def test_each_live_action_key_is_in_the_tables(main_window):
    """Each keyed action of the window shows its own key, held ROI mode aside."""
    cells = {row[0] for _, rows in _md_tables(dt.render_shortcuts()) for row in rows}
    hidden = set(ACTION_KEYS)
    missing = {}
    for name, act in _live_actions(main_window).items():
        stored = act.shortcut().toString()
        if not stored or name in hidden:
            continue
        if name in STATIC_ROWS:
            want_key, cell = STATIC_ROWS[name]
            ok = stored == want_key and cell in cells
        else:
            cell = dt.key_text(stored)
            ok = cell in cells and stored == default_settings.get(name)
        if not ok:
            missing[name] = stored
    assert not missing, f"live keys the guide does not show: {missing}"


@pytest.mark.gui
def test_rows_match_the_live_shortcuts_dialog():
    from PyReconstruct.modules.gui.dialog.shortcuts import shownShortcuts

    hidden = set(ACTION_KEYS)
    assert [
        item for item in dt.help_rows()
        if not (isinstance(item, tuple) and item[0] in hidden)
    ] == shownShortcuts()

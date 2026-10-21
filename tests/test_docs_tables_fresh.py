"""The User Guide's tool and shortcut tables match the app.

``scripts/docs_tables.py`` writes them from the app's own data (the shipped
defaults, the rows of Help > Shortcuts list, the tool palette). The guide said
Ctrl+M for Merge traces for months after the default became Shift+M; this
test is what stops that. When it fails, the fix is one command:

    python3 scripts/docs_tables.py --write

The generator reads the app as source, without Qt. The gui tests at the end
check that reading against a real MainWindow, so a refactor that moves the
data cannot leave the generator reading a stale copy of it.
"""
import importlib.util
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
        f"{dt.GUIDE} does not match the app ({', '.join(stale)}). "
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


def test_every_default_key_is_listed():
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


@pytest.mark.gui
def test_tools_match_the_live_palette(main_window):
    buttons = main_window.mouse_palette.mode_buttons
    live = [name for name, _ in sorted(buttons.items(), key=lambda kv: kv[1][2])]
    assert dt.palette_tools() == live
    for name, act in dt.tool_actions().items():
        assert getattr(main_window, act).shortcut().toString() == default_settings[act]


@pytest.mark.gui
def test_rows_match_the_live_shortcuts_dialog():
    from PyReconstruct.modules.gui.dialog.shortcuts import shownShortcuts

    hidden = set(ACTION_KEYS)
    assert [
        item for item in dt.help_rows()
        if not (isinstance(item, tuple) and item[0] in hidden)
    ] == shownShortcuts()

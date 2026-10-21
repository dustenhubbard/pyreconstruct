#!/usr/bin/env python3
"""Write the User Guide's tool and shortcut tables from PyReconstruct's own data.

The guide's hand-written shortcut table drifted from the app: it said Ctrl+M
for Merge traces after the default became Shift+M, and it never listed nine
keys added later. Every one of those changes went through review; nothing
asked about the guide. So the tables are now generated, and
``tests/test_docs_tables_fresh.py`` fails the moment the committed guide and
the app disagree.

Sources, all read without importing Qt, so this runs on a bare ``python3``:

  * ``datatypes/default_settings.py``, the default key of every action. Run
    as a file: it imports only the standard library.
  * ``gui/dialog/shortcuts.py``, ``help_shortcuts``: the headings, order and
    descriptions the in-app Help > Shortcuts list shows. Read as a literal.
  * ``gui/palette/mouse_palette.py``, the tool buttons in palette order, and
    ``gui/main/main_window.py``, ``mode_shortcuts``: which action picks which
    tool. Read with ``ast``.
  * ``constants/roi_mode.py``, the actions of the held ROI mode.

Hidden tools never appear. The palette and ``mode_shortcuts`` add a held tool
inside an ``if`` (ROI mode, behind PYRECON_ROI_MODE); only the unconditional
calls are read, so a tool added behind any switch stays out until it is
unconditional. The shortcut rows drop the ROI action keys. The environment is
never consulted: launching with the switch set does not change the guide.

Keys are written the way the app writes them on each platform: on macOS Qt
reads Ctrl as Command, Alt as Option and Meta as Control (the same names
``gui/modifiers.display_label`` uses), so a key with any of those shows the
macOS form first, e.g. ``Cmd+Shift+V`` (``Ctrl+Shift+V`` on Windows/Linux).

Usage:
    python3 scripts/docs_tables.py --write   # rewrite the guide's tables
    python3 scripts/docs_tables.py --check   # exit 1 and name the stale ones
"""

import argparse
import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = Path("docs/USER_GUIDE.md")
PKG = Path("PyReconstruct/modules")

FIX_COMMAND = "python3 scripts/docs_tables.py --write"

## Qt's names on macOS for the modifiers it swaps (gui/modifiers.display_label)
MAC_NAMES = {"Ctrl": "Cmd", "Alt": "Option", "Meta": "Control"}


def _load_file(path: Path):
    """Run a stdlib-only module by its path, outside the package (no Qt)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root: Path, rel: str) -> ast.Module:
    return ast.parse((root / PKG / rel).read_text(encoding="utf-8"))


def defaults(root: Path = ROOT) -> dict:
    """The shipped default settings."""
    return _load_file(root / PKG / "datatypes/default_settings.py").default_settings


def hidden_actions(root: Path = ROOT) -> tuple:
    """Action keys of held features, which the guide never shows."""
    return tuple(_load_file(root / PKG / "constants/roi_mode.py").ACTION_KEYS)


def help_rows(root: Path = ROOT) -> list:
    """``help_shortcuts``, the rows of Help > Shortcuts list, as data."""
    for node in _tree(root, "gui/dialog/shortcuts.py").body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "help_shortcuts"
        ):
            return ast.literal_eval(node.value)
    raise LookupError("help_shortcuts not found in gui/dialog/shortcuts.py")


def _unconditional(node: ast.AST):
    """Every node under ``node`` that no ``if`` guards."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.IfExp)):
            continue
        yield child
        yield from _unconditional(child)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == name
            for n in _unconditional(node)
        ):
            return node
    raise LookupError(f"no function calls {name}()")


def palette_tools(root: Path = ROOT) -> list:
    """Tool names on the palette, in button order, held tools left out."""
    func = _function(_tree(root, "gui/palette/mouse_palette.py"), "createModeButton")
    calls = [
        n for n in _unconditional(func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "createModeButton"
    ]
    named = [(c.args[1].value, c.args[0].value) for c in calls]
    return [name for _, name in sorted(named)]


def tool_actions(root: Path = ROOT) -> dict:
    """Tool name -> the action whose key picks it (``mode_shortcuts``)."""
    for node in ast.walk(_tree(root, "gui/main/main_window.py")):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "mode_shortcuts"
        ):
            pairs = {}
            for elt in node.value.elts:
                act, fn = elt.elts
                call = fn.body
                pairs[call.args[0].value] = act.value
            return pairs
    raise LookupError("mode_shortcuts not found in gui/main/main_window.py")


def key_text(stored: str) -> str:
    """A key as the guide writes it: macOS first where macOS names it differently."""
    if not stored:
        return "(none)"
    mac = re.sub(r"\b(Ctrl|Alt|Meta)\b", lambda m: MAC_NAMES[m.group(1)], stored)
    if mac == stored:
        return f"`{stored}`"
    return f"`{mac}` (`{stored}` on Windows/Linux)"


def _modifier_text(stored: str) -> str:
    """A held-modifier setting (``"ctrl+shift"``) in the same form as a key."""
    return "+".join(p.capitalize() for p in stored.split("+") if p)


def _count(n: int) -> str:
    words = "zero one two three four five six seven eight nine ten eleven twelve".split()
    return words[n] if n < len(words) else str(n)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_tools(root: Path = ROOT) -> str:
    """The tool palette table: each tool and the key that picks it."""
    keys = defaults(root)
    acts = tool_actions(root)
    tools = palette_tools(root)
    lines = [
        f"The palette has {_count(len(tools))} tools, top to bottom:",
        "",
        "| Tool | Key |",
        "|---|---|",
    ]
    for name in tools:
        act = acts.get(name)
        lines.append(f"| {name} | {key_text(keys[act]) if act else '(none)'} |")
    return "\n".join(lines)


def shortcut_rows(root: Path = ROOT) -> list:
    """(heading, [(key cell, description)]) per group, as the dialog shows them."""
    keys = defaults(root)
    hidden = set(hidden_actions(root))
    groups = []
    for item in help_rows(root):
        if item is None:
            continue
        if isinstance(item, str):
            groups.append((item.rstrip(":"), []))
            continue
        name, desc = item
        rows = groups[-1][1]
        if name in hidden:
            continue
        if not name:  # the dialog's continuation line of the row above
            key, prev = rows[-1]
            rows[-1] = (key, f"{prev.rstrip('.')}. {desc.rstrip('.')}.")
            continue
        if name in keys:
            stored = keys[name]
            if not stored:
                continue  # no default key; nothing to press
            if not name.endswith("_act"):
                stored = _modifier_text(stored)
        else:
            stored = name  # a literal row: "Page Up", "Ctrl+#, Ctrl+Shift+#"
        rows.append((key_text(stored), desc))
    return [(heading, rows) for heading, rows in groups if rows]


def render_shortcuts(root: Path = ROOT) -> str:
    """Every default shortcut, grouped as Help > Shortcuts list groups them."""
    lines = []
    for heading, rows in shortcut_rows(root):
        lines += [f"### {heading}", "", "| Key | Action |", "|---|---|"]
        lines += [f"| {_cell(key)} | {_cell(desc)} |" for key, desc in rows]
        lines.append("")
    return "\n".join(lines).rstrip()


BLOCKS = {
    "tools": render_tools,
    "shortcuts": render_shortcuts,
}


def _block_re(name: str) -> re.Pattern:
    return re.compile(
        rf"(<!-- generated: {name} .*?-->\n)(.*?)(<!-- /generated: {name} -->)",
        re.DOTALL,
    )


def _tool_headings(text: str, root: Path) -> str:
    """Section 6's tool headings, ``### Knife (`K`)``, with the app's keys."""
    start = text.index("\n## 6. ")
    end = text.index("\n## 7. ", start)
    keys = defaults(root)
    section = text[start:end]
    for name, act in tool_actions(root).items():
        section = re.sub(
            rf"(?m)^(###[^\n]*\b{re.escape(name)} \(`)[^`]*(`\))",
            lambda m: m.group(1) + keys[act] + m.group(2),
            section,
        )
    return text[:start] + section + text[end:]


def render_parts(text: str, root: Path = ROOT) -> dict:
    """Each generated part of the guide -> the guide with only that part fresh."""
    parts = {}
    for name, render in BLOCKS.items():
        pattern = _block_re(name)
        if len(pattern.findall(text)) != 1:
            raise ValueError(f"{GUIDE}: expected one '{name}' block between markers")
        body = render(root) + "\n"
        parts[name] = pattern.sub(lambda m: m.group(1) + body + m.group(3), text)
    parts["tool headings"] = _tool_headings(text, root)
    return parts


def render_guide(text: str, root: Path = ROOT) -> str:
    """The guide text with every generated part rewritten from the app."""
    for name, render in BLOCKS.items():
        body = render(root) + "\n"
        text = _block_re(name).sub(lambda m: m.group(1) + body + m.group(3), text)
    return _tool_headings(text, root)


def stale_parts(text: str, root: Path = ROOT) -> list:
    """Names of the generated parts whose committed text differs from the app."""
    return [name for name, fresh in render_parts(text, root).items() if fresh != text]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the guide's tables")
    mode.add_argument("--check", action="store_true", help="report stale tables (default)")
    args = parser.parse_args(argv)

    path = ROOT / GUIDE
    text = path.read_text(encoding="utf-8")
    if args.write:
        fresh = render_guide(text)
        if fresh != text:
            path.write_text(fresh, encoding="utf-8")
            print(f"wrote {GUIDE}")
        else:
            print(f"{GUIDE} is up to date")
        return 0

    stale = stale_parts(text)
    if stale:
        print(f"{GUIDE}: stale tables: {', '.join(stale)}. Run: {FIX_COMMAND}")
        return 1
    print(f"{GUIDE} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

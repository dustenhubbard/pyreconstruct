"""Every `self.series.<name>(...)` call in the main window resolves on `Series`.

`MainWindow.newAlignment` called `self.series.newAlignment(...)` for years, and
`Series` never had that method. Nothing reached it, so nothing raised. A method
that only fails when called is invisible to the suite until a menu entry or a
script wires it up, at which point the user gets an AttributeError.

This test walks the main-window modules with `ast` and checks that the
attribute of every call on `self.series` exists on the `Series` class. Methods
and properties are class attributes, so `hasattr(Series, name)` is the right
check; instance attributes set in `__init__` are not callable here and are not
reached by this scan.

`ast`, not `re`: a comment or a docstring that names a method is not a call
site, and only a real `Call` node is one.
"""

import ast
from pathlib import Path

from PyReconstruct.modules.datatypes import Series

GUI_MAIN = Path(__file__).resolve().parent.parent / "PyReconstruct" / "modules" / "gui" / "main"


def _series_method_calls(tree):
    """(lineno, name) for every `self.series.<name>(...)` call in a module."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = node.func.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr == "series"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            yield node.lineno, node.func.attr


def test_main_window_series_calls_resolve_on_series():
    modules = sorted(GUI_MAIN.glob("*.py"))
    assert modules, f"no modules found under {GUI_MAIN}"

    missing = []
    seen = 0
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), path.name)
        for lineno, name in _series_method_calls(tree):
            seen += 1
            if not hasattr(Series, name):
                missing.append(f"{path.name}:{lineno} self.series.{name}()")

    assert seen > 0, "the scan found no self.series calls; the pattern is wrong"
    assert not missing, "calls on Series that Series does not define:\n" + "\n".join(missing)

"""The lint gate's `per-file-ignores` must not outlive their reason.

`ruff.toml` carries three F401/F811 ignores. Two are permanent and describe what
those files are: `**/__init__.py` and `main_imports.py` exist to re-export, so
pyflakes calls their imports unused while the rest of the tree depends on them.

The third is temporary. `PyReconstruct/modules/datatypes/objects.py` is ignored
for F811 because `SeriesObject.opacity_3D` is rebound by a `@mode_3D.setter`
decorator, which is a real defect rather than a style finding: the property has
been returning the 3D mode instead of the opacity. The fix is one line and is
already in flight on `fix/seriesobject-setters`, so this pull request left the
file alone rather than racing it.

That is the kind of entry that rots. Once the decorator is corrected the ignore
suppresses nothing, and a stale ignore is worse than no rule at all: it reads
like a known exemption and quietly covers the next redefinition to land in that
file. The test below fails the moment the ignore stops being needed, so removing
it is not something anyone has to remember.

It reads the decorator rather than running ruff. The suite has no ruff to call
(`uvx` fetches the binary in CI), and the decorator is the whole condition.
"""

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUFF_TOML = REPO_ROOT / "ruff.toml"
OBJECTS = REPO_ROOT / "PyReconstruct" / "modules" / "datatypes" / "objects.py"

OBJECTS_KEY = "PyReconstruct/modules/datatypes/objects.py"


def _per_file_ignores():
    cfg = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))
    return cfg.get("lint", {}).get("per-file-ignores", {})


def _opacity_3d_setter_is_misbound() -> bool:
    """True while the `opacity_3D` setter is decorated with the wrong property."""

    tree = ast.parse(OBJECTS.read_text(encoding="utf-8"))

    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name != "opacity_3D":
                continue
            for dec in fn.decorator_list:
                # `@<name>.setter` only; the bare `@property` getter has no attr.
                if (
                    isinstance(dec, ast.Attribute)
                    and dec.attr == "setter"
                    and isinstance(dec.value, ast.Name)
                    and dec.value.id != "opacity_3D"
                ):
                    return True
    return False


def test_the_objects_f811_ignore_is_still_earning_its_place():
    """Drop the objects.py F811 ignore as soon as the rebind is fixed."""

    ignored = OBJECTS_KEY in _per_file_ignores()
    misbound = _opacity_3d_setter_is_misbound()

    if ignored and not misbound:
        raise AssertionError(
            f"ruff.toml still ignores F811 in {OBJECTS_KEY}, but the "
            "`opacity_3D` setter is now decorated with its own property, so "
            "there is nothing left to suppress. Delete the entry from "
            "[lint.per-file-ignores] in ruff.toml; the rule will then confirm "
            "the fix by passing."
        )

    if misbound and not ignored:
        raise AssertionError(
            "`opacity_3D` is still rebound by another property's setter, which "
            f"F811 reports, and {OBJECTS_KEY} is no longer ignored. Fix the "
            "decorator rather than re-adding the ignore."
        )


def test_the_re_export_ignores_are_scoped_to_f401():
    """The two permanent ignores cover unused imports and nothing else.

    Widening either of them to a bare list, or adding F811, would let a genuine
    redefinition through in the largest import blocks in the tree.
    """

    ignores = _per_file_ignores()

    for key in ("**/__init__.py", "PyReconstruct/modules/gui/main/main_imports.py"):
        assert key in ignores, (
            f"{key} is no longer in [lint.per-file-ignores]. It re-exports "
            "names it does not use; F401 reports every one of them."
        )
        assert ignores[key] == ["F401"], (
            f"{key} is ignored for {ignores[key]}, not just F401. Re-export "
            "sites need the unused-import rule silenced and nothing else."
        )

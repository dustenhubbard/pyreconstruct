"""Re-export modules may suppress unused imports, but not redefinitions."""

import tomllib
from pathlib import Path

RUFF_TOML = Path(__file__).resolve().parents[1] / "ruff.toml"


def test_the_re_export_ignores_are_scoped_to_f401():
    """The two permanent ignores cover unused imports and nothing else.

    Widening either of them to a bare list, or adding F811, would let a genuine
    redefinition through in the largest import blocks in the tree.
    """

    cfg = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))
    ignores = cfg.get("lint", {}).get("per-file-ignores", {})

    for key in ("**/__init__.py", "PyReconstruct/modules/gui/main/main_imports.py"):
        assert key in ignores, (
            f"{key} is no longer in [lint.per-file-ignores]. It re-exports "
            "names it does not use; F401 reports every one of them."
        )
        assert ignores[key] == ["F401"], (
            f"{key} is ignored for {ignores[key]}, not just F401. Re-export "
            "sites need the unused-import rule silenced and nothing else."
        )

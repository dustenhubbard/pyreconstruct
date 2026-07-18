"""Menu-label style guard (context-menu UX overhaul, phase 1).

Menu items use the ASCII ellipsis "..." rather than the Unicode "…" so the
whole menu corpus reads consistently. This test scans the modules that define
menu labels and fails if a Unicode ellipsis creeps back in.
"""

from pathlib import Path

import pytest

_GUI = Path(__file__).resolve().parents[1] / "PyReconstruct" / "modules" / "gui"

# Modules whose string literals are (almost) exclusively menu/label text.
MENU_LABEL_FILES = [
    _GUI / "main" / "menubar.py",
    _GUI / "main" / "context_menu_list.py",
    _GUI / "table" / "object.py",
    _GUI / "table" / "section.py",
    _GUI / "table" / "flag.py",
    _GUI / "table" / "trace.py",
    _GUI / "table" / "ztrace.py",
]


@pytest.mark.parametrize("path", MENU_LABEL_FILES, ids=lambda p: p.name)
def test_menu_labels_use_ascii_ellipsis(path):
    text = path.read_text(encoding="utf-8")
    assert "…" not in text, (
        f"{path.name} contains a Unicode ellipsis '…'; use ASCII '...' in menu labels"
    )

"""A damaged old file stays owed across the in-app Restart.

The Restart reloads every ``PyReconstruct.modules`` module in the same
process, and Qt keeps its parse of the file across that reload. The checks
are in ``settings_copy_restart_child.py``, run in a pytest process of its own,
because reloading modules would change the classes every later test in a
shared session sees.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent


def test_a_damaged_old_file_stays_owed_across_the_in_app_restart():
    child = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
            "-c", str(REPO / "pytest.ini"),
            str(TESTS / "settings_copy_restart_child.py"),
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "3 passed" in child.stdout, child.stdout

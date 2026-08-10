"""Tests for scripts/prune_untagged_placeholders.py.

This helper feeds `git push origin :refs/tags/...` in the release workflow, so
every test here is really asking one of two questions: does it catch the orphan,
and can it ever take something load-bearing? The second matters more -- a false
positive deletes a live draft release's only tag.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "prune_untagged_placeholders.py"

_spec = importlib.util.spec_from_file_location("prune_untagged_placeholders", SCRIPT)
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)

# The real leftover, from the v1.21.1 draft.
ORPHAN = "untagged-87b5beb96d79ab5ff1c1"
RELEASE_TAGS = ["v1.21.2-beta-1", "v1.21.1", "v1.21.0", "v1.21.0-beta-7"]


def test_selects_an_orphaned_placeholder():
    assert prune.select([*RELEASE_TAGS, ORPHAN], RELEASE_TAGS) == [ORPHAN]


def test_never_selects_a_placeholder_a_release_points_at():
    """A LIVE draft's placeholder. Deleting this breaks the draft release."""
    live = "untagged-0123456789abcdef0123"
    assert prune.select([*RELEASE_TAGS, live], [*RELEASE_TAGS, live]) == []


def test_empty_in_use_list_selects_nothing():
    """An empty list means the API lookup failed far more often than it means the
    repo has no releases. Guessing wrong here deletes a live draft's tag."""
    assert prune.select([ORPHAN, "v1.21.1"], []) == []
    assert prune.select([ORPHAN], ["", "  "]) == []


def test_never_selects_version_tags():
    assert prune.select(RELEASE_TAGS, RELEASE_TAGS) == []
    assert prune.select(["v1.21.1", "v1.20.4"], ["v9.9.9"]) == []


def test_only_the_exact_placeholder_shape():
    """`untagged-` as a word is not proof; the rest must be hex and nothing else."""
    keep = [
        "untagged-release-notes",        # words, not hex
        "untagged",                      # prefix alone
        "untagged-",                     # empty body
        "untagged-87b5beb9-wip",         # hex then a suffix
        "v1-untagged-87b5beb9",          # not anchored at the start
        "UNTAGGED-87B5BEB9",             # GitHub mints lowercase
    ]
    assert prune.select(keep, ["v1.21.1"]) == []


def test_selects_several_and_preserves_input_order():
    a, b = "untagged-aaaa1111", "untagged-bbbb2222"
    assert prune.select([a, "v1.21.1", b], ["v1.21.1"]) == [a, b]


def test_tolerates_whitespace_and_blank_lines():
    assert prune.select(["  " + ORPHAN + "  ", "", "v1.21.1"], [" v1.21.1 "]) == [ORPHAN]


def _run(stdin, in_use_file):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(in_use_file)],
        input=stdin, capture_output=True, text=True,
    )


def test_cli_end_to_end(tmp_path):
    f = tmp_path / "in_use.txt"
    f.write_text("\n".join(RELEASE_TAGS) + "\n")
    r = _run("\n".join([*RELEASE_TAGS, ORPHAN]) + "\n", f)
    assert r.returncode == 0
    assert r.stdout.split() == [ORPHAN]


def test_cli_missing_in_use_file_is_an_error_not_a_silent_sweep(tmp_path):
    r = _run(ORPHAN + "\n", tmp_path / "does-not-exist.txt")
    assert r.returncode == 2
    assert r.stdout.strip() == ""


def test_cli_requires_the_argument(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT)], input="", capture_output=True, text=True)
    assert r.returncode == 2
    assert r.stdout.strip() == ""

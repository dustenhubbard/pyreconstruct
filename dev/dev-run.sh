#!/usr/bin/env bash
#
# dev-run.sh -- launch PyReconstruct from *this* source tree, no build/installer.
#
# Why this exists
# ---------------
# The `pyrecon_dev` conda env has PyReconstruct installed *editable*
# (`pip install -e .`). A modern setuptools editable install registers a
# meta-path finder (site-packages/__editable___pyreconstruct_*_finder.py) that
# hard-maps `import PyReconstruct` to ONE fixed checkout -- the shared clone at
# ~/projects/pyreconstruct. So running `python PyReconstruct/run.py` from a git
# *worktree* can silently import the OTHER checkout's code, and your edits in
# the worktree never actually run.
#
# The fix: put this worktree's root at the FRONT of PYTHONPATH. The editable
# finder is *appended* to sys.meta_path, which puts it AFTER the built-in
# PathFinder that searches sys.path (PYTHONPATH lands there). PathFinder is
# consulted first, so `import PyReconstruct` resolves to the worktree before the
# editable finder is ever asked. Verified on this box: with the worktree on
# PYTHONPATH, `PyReconstruct.__file__` points into the worktree, not the
# editable checkout. Run `dev/dev-run.sh --check` to confirm at any time.
#
# Usage
# -----
#   dev/dev-run.sh                 # run the app from the worktree holding this script
#   dev/dev-run.sh /path/to/wt     # run the app from a different worktree root
#   dev/dev-run.sh --check         # don't launch; just print which PyReconstruct
#                                  #   would be imported (sanity-check the shadow)
#
# Environment overrides (all optional)
# ------------------------------------
#   PYTHON            interpreter to use (default: `python`). Handy on macOS
#                     where `python` may not be the 3.11 you want.
#   QT_QPA_PLATFORM   Qt platform plugin. Intentionally NOT set here, so the app
#                     uses the real display: your RDP desktop on the Linux
#                     server, the native window server on macOS. Export it
#                     yourself for headless runs, e.g.
#                     `QT_QPA_PLATFORM=offscreen dev/dev-run.sh`.
#
# Portable across Linux and macOS: sticks to POSIX-ish bash with no GNU-only
# flags (no `readlink -f`), so it works with macOS's bundled bash 3.2.

set -euo pipefail

# --- parse the optional first argument --------------------------------------
# $1 is either the --check flag, a worktree-root override, or absent.
check=0
worktree_override=""
case "${1:-}" in
    --check) check=1 ;;
    "")      ;;
    *)       worktree_override="$1" ;;
esac

# --- resolve the worktree root ----------------------------------------------
# This script lives in <worktree>/dev/, so the worktree root is its parent.
# `cd .. && pwd` is the portable way to get an absolute path (no `readlink -f`).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_worktree="$(cd "$script_dir/.." && pwd)"
worktree="${worktree_override:-$default_worktree}"

run_py="$worktree/PyReconstruct/run.py"
if [ ! -f "$run_py" ]; then
    echo "dev-run.sh: no PyReconstruct/run.py under '$worktree'" >&2
    echo "  (expected a PyReconstruct worktree root; pass one as the first argument)" >&2
    exit 1
fi

# --- defeat the editable-install shadow -------------------------------------
# Prepend the worktree, preserving any PYTHONPATH the caller already set.
export PYTHONPATH="$worktree${PYTHONPATH:+:$PYTHONPATH}"

python_bin="${PYTHON:-python}"

# --check: prove which package will be imported, then exit without launching.
if [ "$check" -eq 1 ]; then
    exec "$python_bin" -c 'import PyReconstruct; print(PyReconstruct.__file__)'
fi

# Launch the app straight from source (same entry the console script and the
# installer launch scripts use). `exec` replaces this shell so Ctrl-C and exit
# codes pass straight through to Python.
echo "dev-run.sh: launching from $worktree" >&2
exec "$python_bin" "$run_py"

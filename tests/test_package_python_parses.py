"""Every ``.py`` file shipped in the package must parse.

This exists because a shipped asset script sat broken in the repository for
years. ``assets/misc/zarr_to_jser.py`` (since deleted) line 82 read::

    tform = alignment[str(snum)])

an unmatched ``)`` that makes the whole file a ``SyntaxError``. It was
introduced by dropping the ``Transform(`` from ``Transform(alignment[...])``
in a documentation commit, and nothing noticed: the file is a standalone
script that no module imports, so no import, no test, and no linter run
scoped to imported code ever looked at it. A user following the autoseg
workflow would have been the first to find out.

The paren was the symptom. The absence of any gate over non-imported code was
the defect, so the guard is deliberately wider than the one file that was
broken: it walks the **entire** ``PyReconstruct`` package, plus ``dev/assets/``,
rather than just the directory the break was in. Scripts can appear anywhere,
and "is this file on an import path?" is not a question the test should have to
answer -- compiling everything makes the answer irrelevant.

``dev/assets/`` is walked because the retired script directories moved there on
2026-08-06, out of the package root, so that nothing can pull them into a wheel.
That move took them out of the package walk, which is exactly the "moved out
from under the package root" regression
``test_bundled_scripts_are_covered_by_the_walk`` was written to catch. They are
no longer shipped, but they are still maintained code in this repository, so the
parse gate follows them rather than quietly dropping them.

Two implementation notes:

  * It uses the builtin ``compile()`` on the source text, **not**
    ``py_compile``. ``py_compile`` writes bytecode into ``__pycache__``
    directories inside the source tree, which would leave untracked residue
    in the repository for every non-imported script it touched. ``compile()``
    performs the same parse and writes nothing.

  * It is one test over all files rather than a parametrized test per file.
    Compiling the whole package is a fraction of a second, and a single
    assertion can report *every* broken file at once instead of stopping at
    the first, which is what someone fixing a bad merge actually wants.

Note what this does and does not claim. Parsing is not importing: a file that
compiles may still fail at import or at run time (every script in
``dev/assets/misc/`` opens hardcoded local paths at module level, so none of
them can be imported or executed whole here). Syntactic validity is the floor, and
the floor is what was missing. A second gate goes one step higher for the
directory that housed the broken file: each script's module-level import
statements are extracted and actually executed -- see
``test_bundled_misc_script_imports_execute``.
"""

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "PyReconstruct"
DEV_ASSETS = REPO_ROOT / "dev" / "assets"


def test_every_package_python_file_parses():
    """No ``.py`` file under ``PyReconstruct/`` or ``dev/assets/`` may be a ``SyntaxError``."""

    assert PACKAGE_ROOT.is_dir(), f"package root not found: {PACKAGE_ROOT}"
    assert DEV_ASSETS.is_dir(), f"dev assets not found: {DEV_ASSETS}"

    sources = sorted(PACKAGE_ROOT.rglob("*.py")) + sorted(DEV_ASSETS.rglob("*.py"))

    # Guard against the walk silently matching nothing (a moved package
    # directory would otherwise make this test vacuously pass forever).
    assert len(sources) > 100, (
        f"expected the package walk to find many modules, found {len(sources)}"
    )

    failures = []

    for path in sources:
        rel = path.relative_to(REPO_ROOT)
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            failures.append(f"{rel}: not valid UTF-8 ({e})")
            continue
        try:
            compile(source, str(path), "exec")
        except SyntaxError as e:
            failures.append(f"{rel}:{e.lineno}: {e.msg}")

    assert not failures, (
        f"{len(failures)} of {len(sources)} shipped Python file(s) do not parse:\n  "
        + "\n  ".join(failures)
    )


def test_bundled_scripts_are_covered_by_the_walk():
    """The walk must reach the non-imported scripts, which are the point of it.

    The asset trees hold standalone scripts that no module imports -- the blind
    spot the broken file lived in. If a refactor moved them somewhere neither
    walk reaches, the test above would keep passing while covering nothing that
    needs covering, so assert the blind spot is still in scope.

    The retired scripts moved to ``dev/assets/`` on 2026-08-06 and the live ones
    stayed under the package, so both roots are asserted: the point is that
    every non-imported script is under *some* walked root, not which one.
    """

    covered = {
        p.relative_to(REPO_ROOT).as_posix()
        for root in (PACKAGE_ROOT, DEV_ASSETS)
        for p in root.rglob("*.py")
    }

    assert "dev/assets/misc/jser_to_zarr_v2.py" in covered
    assert "dev/assets/misc/crop_zarr.py" in covered
    assert "PyReconstruct/assets/scripts/start_process.py" in covered

    asset_scripts = {
        p for p in covered
        if p.startswith("dev/assets/") or p.startswith("PyReconstruct/assets/")
    }
    assert len(asset_scripts) > 5, (
        f"expected several bundled asset scripts in scope, found {sorted(asset_scripts)}"
    )


def test_bundled_misc_script_imports_execute():
    """Every ``dev/assets/misc/`` script's module-level imports must actually resolve.

    The file that hid a SyntaxError also carried an ``ImportError``:
    ``from PyReconstruct.modules.backend.func import reducePoints``, a name
    ``backend.func`` has never exported (the function lives in
    ``modules/calc/grid.py`` and is exported from ``PyReconstruct.modules.calc``).
    Parsing cannot catch that class of rot, and these scripts cannot be imported
    whole -- their top level immediately opens hardcoded local paths -- so this
    test extracts the module-level import statements with ``ast`` and executes
    exactly those, alone, in a subprocess, once per script. Every dependency
    they name (``cv2``, ``numpy``, ``zarr``, ``PySide6``, the PyReconstruct
    modules) is part of this project's own environment, so a failure means a
    script names something that does not exist.

    Scoped to ``dev/assets/misc/`` rather than all of the asset trees: the wider
    tree holds scripts written against third-party tooling that is deliberately
    not a dependency of this project (``dev/assets/scripts/img/mask.py`` imports
    ``colorama``), so a repo-wide version of this gate would report absent
    optional tooling as rot. ``dev/assets/misc/`` is the set of scripts written
    against *this* codebase's own API, which is the API that drifts under them.
    """

    directory = DEV_ASSETS / "misc"
    scripts = sorted(directory.glob("*.py"))

    # guard the glob: an empty directory would make this vacuously pass
    assert len(scripts) >= 3, f"expected several scripts in {directory}, found {scripts}"

    failures = []

    for path in scripts:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stmts = [
            ast.unparse(node) for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        if not stmts:
            continue

        proc = subprocess.run(
            [sys.executable, "-c", "\n".join(stmts)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),  # repo root, so `import PyReconstruct` resolves
            timeout=180,
        )
        if proc.returncode != 0:
            rel = path.relative_to(REPO_ROOT).as_posix()
            failures.append(f"{rel}:\n{proc.stderr.strip()}")

    assert not failures, (
        f"{len(failures)} of {len(scripts)} bundled misc script(s) name an import "
        "that does not execute:\n" + "\n".join(failures)
    )

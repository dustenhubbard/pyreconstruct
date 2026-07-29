"""Every ``.py`` file shipped in the package must parse.

This exists because a shipped asset script sat broken in the repository for
years. ``assets/misc/zarr_to_jser.py`` line 82 read::

    tform = alignment[str(snum)])

an unmatched ``)`` that makes the whole file a ``SyntaxError``. It was
introduced by dropping the ``Transform(`` from ``Transform(alignment[...])``
in a documentation commit, and nothing noticed: the file is a standalone
script that no module imports, so no import, no test, and no linter run
scoped to imported code ever looked at it. A user following the autoseg
workflow would have been the first to find out.

The paren was the symptom. The absence of any gate over non-imported code was
the defect, so the guard is deliberately wider than the one file that was
broken: it walks the **entire** ``PyReconstruct`` package rather than just
``assets/``. Scripts can appear anywhere, and "is this file on an import
path?" is not a question the test should have to answer -- compiling
everything makes the answer irrelevant.

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
compiles may still fail at import or at run time (``zarr_to_jser.py``
requires ``cv2``, ``zarr``, and hardcoded local paths, so it cannot be
imported or executed here). Syntactic validity is the floor, and the floor is
what was missing.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "PyReconstruct"


def test_every_package_python_file_parses():
    """No ``.py`` file under ``PyReconstruct/`` may be a ``SyntaxError``."""

    assert PACKAGE_ROOT.is_dir(), f"package root not found: {PACKAGE_ROOT}"

    sources = sorted(PACKAGE_ROOT.rglob("*.py"))

    # Guard against the walk silently matching nothing (a moved package
    # directory would otherwise make this test vacuously pass forever).
    assert len(sources) > 100, (
        f"expected the package walk to find many modules, found {len(sources)}"
    )

    failures = []

    for path in sources:
        rel = path.relative_to(PACKAGE_ROOT.parent)
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

    ``assets/`` holds standalone scripts that no module imports -- the blind
    spot the broken file lived in. If a refactor moved them out from under
    the package root, the test above would keep passing while covering
    nothing that needs covering, so assert the blind spot is still in scope.
    """

    covered = {p.relative_to(PACKAGE_ROOT).as_posix() for p in PACKAGE_ROOT.rglob("*.py")}

    assert "assets/misc/zarr_to_jser.py" in covered
    assert "assets/misc/jser_to_zarr_v2.py" in covered

    asset_scripts = {p for p in covered if p.startswith("assets/")}
    assert len(asset_scripts) > 5, (
        f"expected several bundled asset scripts in scope, found {sorted(asset_scripts)}"
    )

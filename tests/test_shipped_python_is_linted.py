"""Anything the package ships must be in the linter's scope.

`ruff.toml` used to carry `extend-exclude = ["PyReconstruct/assets"]`, on the
stated grounds that the bundled helper scripts are "not on any import path".
That is true and irrelevant: `[tool.setuptools.package-data]` ships
`assets/**/*`, so all 18 of those `.py` files went into every wheel and every
installer while the CI lint gate never opened one. Shipped code with no gate
over it is the worst of both, and it was not hypothetical: two of the scripts
reached users broken, one of them with a `SyntaxError` and hardcoded Windows
paths that had survived since 2023.

The exclusion was also unnecessary. The critical-error set (`E9`, `F63`, `F7`,
`F82`) passes clean over `PyReconstruct/assets` as it stands, so removing the
exclusion needed no code change at all. That is what makes this a configuration
defect rather than a backlog of broken files.

The tests below pin the four ways the fix could silently come undone. Every one
of them fails open, which is why they are worth writing: the wheel keeps
building, the suite keeps passing, and the only symptom is unlinted code
arriving on a user's machine again.

They read the configuration files as TOML and as text rather than building a
wheel. `setuptools` is not in the `test` extra, so an in-process `build_py` run
is not available, and shelling out to `uv build` would need the network. The
wheel contents were verified by hand instead, with a before/after build; what is
pinned here is the configuration that produced them.
"""

import ast
import tomllib
from pathlib import Path
from pathlib import PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "PyReconstruct"
PYPROJECT = REPO_ROOT / "pyproject.toml"
RUFF_TOML = REPO_ROOT / "ruff.toml"
SPEC = REPO_ROOT / "packaging" / "PyReconstruct.spec"


def _setuptools_cfg():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["setuptools"]


def test_no_ruff_exclusion_shadows_the_package():
    """No ruff exclusion may cover a path inside the shipped package."""

    ruff_cfg = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))

    # ruff honors these at the top level and again under [lint]. Read both, so
    # moving the exclusion one table down does not slip past.
    patterns = [
        pattern
        for table in (ruff_cfg, ruff_cfg.get("lint", {}))
        for key in ("exclude", "extend-exclude")
        for pattern in table.get(key, [])
    ]

    offenders = [
        p for p in patterns
        if PurePosixPath(p.strip("/")).parts[:1] == ("PyReconstruct",)
    ]

    assert not offenders, (
        "ruff.toml excludes paths inside the shipped package: "
        f"{offenders}. The package ships them, so the lint gate has to see "
        "them. To retire a bundled script, stop shipping it (packages.find "
        "exclude plus exclude-package-data) rather than hiding it from ruff."
    )


# Every entry is reached from the running app. The comment is the call site, so
# a reviewer can re-check the claim without grepping for it.
LOAD_BEARING = {
    # imported by modules/gui/main/main_imports.py, which re-exports
    # randomize_project and derandomize_project for the File > Utilities items
    "assets/scripts/projects/__init__.py",
    "assets/scripts/projects/randomize.py",
    "assets/scripts/projects/derandomize.py",
    # launched as a subprocess by modules/gui/main/main_window.py at two sites,
    # the TIFF-to-zarr converter and the neuroglancer zarr export
    "assets/scripts/start_process.py",
    # start_process.py dispatches to these two on its argv[1]
    "assets/scripts/convert_zarr/zarree-2.py",
    "assets/scripts/create_ng_zarr/create_ng_zarr.py",
    # imported by create_ng_zarr.py
    "assets/scripts/create_ng_zarr/parser.py",
    "assets/scripts/create_ng_zarr/utils.py",
}


def _retired_dirs():
    """Asset directories deliberately kept out of the distribution.

    Read from `packages.find`'s `exclude`, which is the one place that names
    them as package paths. Returned relative to the `PyReconstruct` package,
    e.g. `assets/misc`.
    """

    excluded = _setuptools_cfg()["packages"]["find"]["exclude"]

    dirs = set()
    for dotted in excluded:
        parts = dotted.split(".")
        assert parts[0] == "PyReconstruct", dotted
        dirs.add("/".join(parts[1:]))

    assert dirs, "packages.find lists no excluded packages"
    return dirs


def test_load_bearing_asset_scripts_still_ship():
    """Retiring bundled scripts must not drop one the app actually runs."""

    cfg = _setuptools_cfg()

    # The broad include is what guarantees a newly added asset ships by
    # default. Replacing it with an explicit list is how assets get dropped by
    # omission, so require it to still be there.
    includes = cfg["package-data"]["PyReconstruct"]
    assert "assets/**/*" in includes, (
        f"the blanket assets include is gone from package-data: {includes}"
    )

    retired = _retired_dirs()

    for rel in sorted(LOAD_BEARING):
        assert (PACKAGE_ROOT / rel).is_file(), f"missing from the tree: {rel}"

        shadowed = [d for d in retired if rel.startswith(f"{d}/")]
        assert not shadowed, (
            f"{rel} is reached from the running app, but packages.find "
            f"excludes the directory it lives in: {shadowed}"
        )


def test_every_retired_directory_is_excluded_three_times_over():
    """All three `exclude-package-data` keys must cover every retired directory.

    Three independent mechanisms put these files in the wheel, and each is
    filtered by a different key (see the comment above `packages.find` in
    `pyproject.toml`). Dropping any one key silently reships the directory, so
    assert the three tables agree rather than trusting them to stay in step.
    """

    excludes = _setuptools_cfg()["exclude-package-data"]
    retired = _retired_dirs()

    # Keyed on the top-level package: patterns are relative to PyReconstruct/.
    assert set(excludes["PyReconstruct"]) == {f"{d}/*" for d in retired}

    # Keyed on each intermediate package that a retired directory sits under:
    # patterns are relative to that package's own directory.
    for parent in {d.rsplit("/", 1)[0] for d in retired}:
        key = "PyReconstruct." + parent.replace("/", ".")
        expected = {
            d[len(parent) + 1:] + "/*" for d in retired
            if d.startswith(f"{parent}/")
        }
        assert set(excludes.get(key, [])) == expected, (
            f"exclude-package-data key {key!r} does not cover {expected}"
        )


def _spec_dev_only_dirs():
    """`_DEV_ONLY_ASSET_DIRS` from the PyInstaller spec, read without executing it.

    The spec is not importable: PyInstaller injects `SPECPATH` and the
    `Analysis` machinery into its namespace at build time. Pulling the one
    assignment out with `ast` avoids needing any of that.
    """

    tree = ast.parse(SPEC.read_text(encoding="utf-8"))

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(t, ast.Name) and t.id == "_DEV_ONLY_ASSET_DIRS"
            for t in node.targets
        ):
            return {"/".join(parts) for parts in ast.literal_eval(node.value)}

    raise AssertionError("_DEV_ONLY_ASSET_DIRS not found in the PyInstaller spec")


def test_installer_and_wheel_skip_the_same_asset_dirs():
    """The installers' skip list and the wheel's exclusions must agree.

    `checker` is the one deliberate difference: the wheel keeps it because the
    source test suite uses those `.jser` files as fixtures, while the installers
    have skipped its ~1.8 MB since they were introduced. Every other skipped
    directory has to appear on both sides or the two distributions ship
    different code.
    """

    spec_dirs = _spec_dev_only_dirs()
    wheel_dirs = {d[len("assets/"):] for d in _retired_dirs()}

    assert spec_dirs - {"checker"} == wheel_dirs, (
        "the installer skip list and the wheel exclusions disagree.\n"
        f"  spec:  {sorted(spec_dirs)}\n"
        f"  wheel: {sorted(wheel_dirs)}"
    )

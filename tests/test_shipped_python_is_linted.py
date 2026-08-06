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

**Changed 2026-08-06.** The four dev-only asset directories no longer sit inside
the package at all; they moved to `dev/assets/`. That replaces three
`exclude-package-data` tables and a `packages.find` `exclude` list with
exclusion by construction: `packages.find` only looks inside `PyReconstruct*`,
and every `package-data` glob resolves relative to a package directory, so
`dev/` is unreachable by any of the three mechanisms that previously each needed
their own entry. The old tests here asserted the three tables agreed with each
other; there are no tables left to disagree, so what is pinned now is that the
directories really are outside the package and that moving them did not drop
them out of the linter.

The tests below pin the ways the fix could silently come undone. Every one of
them fails open, which is why they are worth writing: the wheel keeps building,
the suite keeps passing, and the only symptom is unlinted code arriving on a
user's machine again, or a retired directory quietly moving back inside the
package root.

They read the configuration files as TOML and as text rather than building a
wheel. `setuptools` is not in the `test` extra, so an in-process `build_py` run
is not available, and shelling out to `uv build` would need the network. The
wheel contents were verified by hand instead, with a before/after build; what is
pinned here is the configuration that produced them.
"""

import tomllib
from pathlib import Path
from pathlib import PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "PyReconstruct"
DEV_ASSETS = REPO_ROOT / "dev" / "assets"
PYPROJECT = REPO_ROOT / "pyproject.toml"
RUFF_TOML = REPO_ROOT / "ruff.toml"
SPEC = REPO_ROOT / "packaging" / "PyReconstruct.spec"

# Retired on 2026-08-06, relative to `dev/assets/`. These are the directories
# that used to be subtracted from the distribution by configuration and are now
# simply not inside it.
RETIRED_DIRS = {
    "misc",
    "scripts/img",
    "scripts/contours_from_labels",
    "checker",
}


def _setuptools_cfg():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["setuptools"]


def _ruff_exclusions():
    ruff_cfg = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))

    # ruff honors these at the top level and again under [lint]. Read both, so
    # moving the exclusion one table down does not slip past.
    return [
        pattern
        for table in (ruff_cfg, ruff_cfg.get("lint", {}))
        for key in ("exclude", "extend-exclude")
        for pattern in table.get(key, [])
    ]


def test_no_ruff_exclusion_shadows_the_package():
    """No ruff exclusion may cover a path inside the shipped package."""

    offenders = [
        p for p in _ruff_exclusions()
        if PurePosixPath(p.strip("/")).parts[:1] == ("PyReconstruct",)
    ]

    assert not offenders, (
        "ruff.toml excludes paths inside the shipped package: "
        f"{offenders}. The package ships them, so the lint gate has to see "
        "them. To retire a bundled script, stop shipping it (move it out of "
        "the package root, to dev/assets/) rather than hiding it from ruff."
    )


def test_no_ruff_exclusion_shadows_the_retired_assets():
    """The retired directories must stay linted after moving out of the package.

    Moving them out of `PyReconstruct/` is what keeps them out of the wheel, but
    the stated deal (see the comment above `packages.find` in `pyproject.toml`)
    is that they stay in the repository, stay linted, and keep working from a
    checkout. Excluding `dev/` from ruff would quietly cancel the middle third
    and put these scripts back in exactly the unlinted state that shipped two of
    them broken.
    """

    offenders = [
        p for p in _ruff_exclusions()
        if PurePosixPath(p.strip("/")).parts[:1] == ("dev",)
    ]

    assert not offenders, (
        f"ruff.toml excludes paths under dev/: {offenders}. The retired asset "
        "scripts live there and are still maintained code."
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

    for rel in sorted(LOAD_BEARING):
        assert (PACKAGE_ROOT / rel).is_file(), f"missing from the tree: {rel}"


def test_retired_directories_live_outside_the_package():
    """The retired directories must be under `dev/`, not under the package root.

    This is the whole mechanism. `package-data`'s `assets/**/*` glob is resolved
    relative to `PyReconstruct/`, so a directory that is not under it cannot be
    swept into the wheel however the globs are written. Moving one back inside
    would silently reship it, and the blanket include means it would need no
    other configuration change to do so.
    """

    for rel in sorted(RETIRED_DIRS):
        assert (DEV_ASSETS / rel).is_dir(), f"retired directory missing: dev/assets/{rel}"
        assert not (PACKAGE_ROOT / "assets" / rel).exists(), (
            f"assets/{rel} is back inside the package root, where the blanket "
            "`assets/**/*` package-data include will ship it again"
        )


def test_no_asset_exclusion_tables_have_crept_back():
    """Exclusion tables are the mechanism this move replaced; they should be gone.

    Their absence is load-bearing as documentation rather than as behavior: an
    `exclude-package-data` entry naming an asset directory means someone put a
    dev-only directory back inside the package and reached for the old, weaker
    guarantee instead of the new one. Fail loudly rather than let the two
    mechanisms coexist and rot against each other.
    """

    cfg = _setuptools_cfg()

    assert "exclude" not in cfg["packages"]["find"], (
        "packages.find has an `exclude` list again. Retired directories now "
        "live outside the package root; nothing inside it should need excluding."
    )
    assert "exclude-package-data" not in cfg, (
        "an exclude-package-data table is back in pyproject.toml. Retired "
        "directories now live in dev/assets/, which no package-data glob reaches."
    )


def test_installer_spec_has_no_asset_skip_list():
    """The installers and the wheel must agree by construction, not by two lists.

    `packaging/PyReconstruct.spec` used to carry `_DEV_ONLY_ASSET_DIRS`, a skip
    list that had to be kept in step with the wheel's exclusions by hand, and
    the two deliberately disagreed on `checker` (the wheel shipped its ~1.8 MB
    of fixtures; the installers did not). Both lists are gone: the spec now
    walks `PyReconstruct/assets` unfiltered, and that walk reaches nothing
    dev-only because nothing dev-only is in there any more.
    """

    spec_text = SPEC.read_text(encoding="utf-8")

    assert "_DEV_ONLY_ASSET_DIRS" not in spec_text, (
        "the PyInstaller spec has an asset skip list again; the retired "
        "directories are supposed to be absent from the tree it walks"
    )

    # The spec bundles every file under PyReconstruct/assets. Assert that walk
    # picks up no retired directory, which is what makes the skip list needless.
    bundled = {
        p.relative_to(PACKAGE_ROOT / "assets").as_posix()
        for p in (PACKAGE_ROOT / "assets").rglob("*")
        if p.is_file()
    }
    for rel in sorted(RETIRED_DIRS):
        assert not any(b.startswith(f"{rel}/") for b in bundled), (
            f"the installer's asset walk reaches assets/{rel}, which is retired"
        )

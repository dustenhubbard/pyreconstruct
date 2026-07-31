"""Every version heading in the notes must name a release that exists.

``WHATS_NEW.md`` carried ``## [1.20.5rc1]`` for twenty-six days. The version was
never tagged and never released: the section was written the day 1.20.4 shipped,
the line then moved to the 1.21.0 betas, and the heading stayed behind. It was
found only because an unrelated change made the older sections visible again.
Nothing in the repository knew the difference between a heading for a release
and a heading for a release that had been abandoned.

The rule: every ``## [x.y.z]`` heading other than ``[Unreleased]`` must
correspond to a git tag.

Two things make that less simple than it sounds.

**The heading is written before the tag exists.** That is the normal order and
it happened again for beta-6: the notes were merged, and the tag was cut from
the merged result. A check that demands a tag for every heading fails every
release-notes pull request there will ever be, which makes it a check that gets
removed rather than satisfied.

The grace here is bounded by the *next tag*, not by wall-clock time: a heading
whose version is above every existing tag is staged, and is reported rather than
failed. As soon as any newer tag exists, the grace lapses and the heading has to
have its own. That boundary is the exact condition under which a staged heading
turns into a wrong one, and it is why this catches ``1.20.5rc1``. On the day it
was written, 1.20.5rc1 was above every tag (the newest was v1.20.4) and staging
it was legitimate; nobody could have known then that it would never ship. Three
days later ``v1.21.0-beta-1`` was tagged, 1.20.5rc1 stopped being the newest
thing named anywhere, and this check fails from that moment until the section is
retired. Twenty-three of its twenty-six days would have been red.

The alternatives were worse. Comparing only against the previous tag never
notices an abandoned pre-release at all. Running on a schedule instead of per
pull request delays the signal by up to a day and puts it somewhere nobody is
looking, and does not remove the ordering problem, it only moves it.

**A tag and a heading spell the same version differently.** The tag is
``v1.21.0-beta-6``; the version baked into the application is ``1.21.0b6``. Both
parse to the same PEP 440 version, which is how the What's-new dialog already
matches a heading to the running version. This reuses that: ``_safe_version``
and ``parse_all_sections`` come from ``first_launch`` rather than being
reimplemented here, so the two can never disagree about what a heading means.

The check needs tags to be present, which a shallow clone does not have by
default. ``.github/workflows/test.yml`` passes ``fetch-tags: true`` for exactly
this. An empty tag list is an error rather than a skip: this check has one way
to fail open and that is it.
"""

import subprocess
from pathlib import Path

import pytest

from PyReconstruct.modules.gui.main.first_launch import (
    _normalize_version,
    _safe_version,
    parse_all_sections,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES_FILES = ("WHATS_NEW.md", "CHANGELOG.md")

# Not a version, and never expected to be a tag.
UNRELEASED = "unreleased"


def repo_tag_versions(repo_root=REPO_ROOT):
    """Every tag in the repository, as parsed versions.

    Returns ``(versions, raw_tags)``. A tag that is not a version (a branch-like
    or dated tag) is dropped from ``versions`` and kept in ``raw_tags``.
    """
    out = subprocess.run(
        ["git", "-C", str(repo_root), "tag", "--list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    raw_tags = [t.strip() for t in out.splitlines() if t.strip()]
    versions = set()
    for tag in raw_tags:
        parsed = _safe_version(_normalize_version(tag))
        if parsed is not None:
            versions.add(parsed)
    return versions, raw_tags


def classify_headings(text, tag_versions):
    """Sort one notes file's headings into released, staged, and missing.

    ``tag_versions`` is a set of parsed versions. Returns a dict with:

      ``released``    heading names that match a tag
      ``staged``      heading names above every tag: written, not yet cut
      ``missing``     heading names at or below the newest tag with no tag
      ``unparseable`` heading names that are not versions at all

    ``[Unreleased]`` is skipped: it is the Keep a Changelog holding area and is
    never a tag by design.
    """
    result = {"released": [], "staged": [], "missing": [], "unparseable": []}
    newest_tag = max(tag_versions) if tag_versions else None

    for section in parse_all_sections(text):
        name = section["version"]
        if name.strip().lower() == UNRELEASED:
            continue
        parsed = _safe_version(_normalize_version(name))
        if parsed is None:
            result["unparseable"].append(name)
        elif parsed in tag_versions:
            result["released"].append(name)
        elif newest_tag is not None and parsed > newest_tag:
            result["staged"].append(name)
        else:
            result["missing"].append(name)
    return result


@pytest.fixture(scope="module")
def tag_versions():
    versions, raw_tags = repo_tag_versions()
    if not raw_tags:
        pytest.fail(
            "no git tags in this checkout, so every heading would pass for the "
            "wrong reason. In CI, pass `fetch-tags: true` to actions/checkout; "
            "locally, run `git fetch --tags`."
        )
    if not versions:
        pytest.fail(f"no tag parses as a version: {sorted(raw_tags)}")
    return versions


@pytest.mark.parametrize("filename", NOTES_FILES)
def test_every_notes_heading_names_a_real_release(filename, tag_versions):
    """No heading may claim a version that was never tagged."""

    path = REPO_ROOT / filename
    assert path.is_file(), f"{filename} is missing from the repository root"

    found = classify_headings(path.read_text(encoding="utf-8"), tag_versions)

    assert not found["unparseable"], (
        f"{filename}: heading(s) not parseable as a version: "
        f"{found['unparseable']}. A `## [x]` heading is either `[Unreleased]` "
        f"or a version."
    )

    assert not found["missing"], (
        f"{filename}: {found['missing']} has no git tag, and is not the newest "
        f"thing in the file, so it is not a release waiting to be cut. Either "
        f"the tag was never created and the section should be retired (this is "
        f"what happened to `## [1.20.5rc1]`), or the heading is misspelled. "
        f"Tag spelling does not have to match: `v1.21.0-beta-6` and `1.21.0b6` "
        f"are the same version here."
    )


@pytest.mark.parametrize("filename", NOTES_FILES)
def test_staged_headings_are_reported(filename, tag_versions, capsys):
    """A heading above every tag is allowed, and is printed so it stays visible.

    This never fails. It exists so that a section sitting unreleased for months
    is at least named on every run, rather than being invisible until somebody
    reads the whole file. ``CHANGELOG.md`` has one today: ``## [1.21.0]``,
    staged by the release-notes consolidation with a placeholder date.
    """
    path = REPO_ROOT / filename
    found = classify_headings(path.read_text(encoding="utf-8"), tag_versions)
    if found["staged"]:
        with capsys.disabled():
            print(f"\n{filename}: staged, not yet tagged: {found['staged']}")

"""The README, the website front page and the User Guide name one stable release.

Each of the three files carries the current stable version three ways: a bold
callout (``current stable release, **v1.25.0**``), the download path
(``releases/download/v1.25.0/``) and the versioned asset names
(``PyReconstruct-1.25.0-macOS-arm64.dmg``). ``download-links-bump.yml`` rewrites
all three shapes in all three files when a stable release publishes, and the
site and the guide trailed the README by two releases before that workflow
existed. This pins what the workflow maintains, so a hand edit to one file, or a
bump that misses a shape, fails the suite instead of shipping a link that 404s.

Three things are checked. Every file names exactly one version in each shape,
and it is the same version across the three files. Every versioned asset name
in any file carries that version. The four installer names (the Windows
installer, the two macOS disk images and the Linux AppImage) are the targets of
download links in all three files, read from the link destinations and not from
their labels, since a label can spell the right name over a link to the wrong
file; every destination names one of the known assets. The README alone adds
the from-source tarball, and nothing here requires the other two to link it.

The regexes are the bump workflow's own three, read back, so the test and the
workflow cannot agree on different text.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The three files the bump workflow edits (its FILES array).
RELEASE_LINE_FILES = ("README.md", "docs/USER_GUIDE.md", "docs/index.md")

CALLOUT_RE = re.compile(r"current stable release, \*\*v(\d+\.\d+\.\d+)\*\*")
DOWNLOAD_PATH_RE = re.compile(r"releases/download/v(\d+\.\d+\.\d+)/")
ASSET_RE = re.compile(r"PyReconstruct-(\d+\.\d+\.\d+)-((?:Windows|macOS|Linux|linux)[\w.-]*)")
# A download link's destination: the release path and the file it points at.
DESTINATION_RE = re.compile(r"releases/download/v(\d+\.\d+\.\d+)/([^)\s\"'<>]+)")

# Asset names, version stripped, that every one of the three files links.
INSTALLERS_IN_EVERY_FILE = frozenset(
    {
        "Windows-x86_64-Setup.exe",
        "macOS-arm64.dmg",
        "macOS-x86_64.dmg",
        "linux-x86_64.AppImage",
    }
)
# Every asset a download link may point at: the installers and the tarball.
KNOWN_ASSETS = INSTALLERS_IN_EVERY_FILE | {"Linux-installer.tar.gz"}


def _read(name, root=ROOT):
    return (root / name).read_text(encoding="utf-8")


def release_lines(text):
    """``(callout versions, download path versions, [(version, asset)])`` of one file."""
    return (
        set(CALLOUT_RE.findall(text)),
        set(DOWNLOAD_PATH_RE.findall(text)),
        ASSET_RE.findall(text),
    )


def linked_assets(text, version):
    """``(assets linked, bad destinations)`` from the download link destinations.

    An asset is the destination's file name with ``PyReconstruct-<version>-``
    removed. A destination whose file is not a known asset of ``version`` is
    returned in the second list.
    """
    assets, bad = set(), []
    prefix = f"PyReconstruct-{version}-"
    for path_version, name in DESTINATION_RE.findall(text):
        asset = name[len(prefix):] if name.startswith(prefix) else None
        if path_version != version or asset not in KNOWN_ASSETS:
            bad.append(f"releases/download/v{path_version}/{name}")
        else:
            assets.add(asset)
    return assets, bad


def check(texts):
    """The problems in ``{file name: text}``; an empty list means they agree."""
    problems = []
    versions = {}
    for name, text in texts.items():
        callouts, paths, assets = release_lines(text)
        asset_versions = {v for v, _ in assets}
        if len(callouts) != 1:
            problems.append(f"{name}: expected one stable-release callout, found {sorted(callouts)}")
        if len(paths) != 1:
            problems.append(f"{name}: expected one download path version, found {sorted(paths)}")
        if len(asset_versions) != 1:
            problems.append(f"{name}: expected one version in asset names, found {sorted(asset_versions)}")
        named = callouts | paths | asset_versions
        if len(named) != 1:
            problems.append(f"{name}: callout, download path and asset names disagree: {sorted(named)}")
            continue
        version = next(iter(named))
        versions[name] = version
        linked, bad = linked_assets(text, version)
        for destination in bad:
            problems.append(f"{name}: links an unknown release file: {destination}")
        missing = INSTALLERS_IN_EVERY_FILE - linked
        if missing:
            problems.append(f"{name}: does not link {sorted(missing)}")
    if len(set(versions.values())) > 1:
        problems.append(f"the files name different stable versions: {versions}")
    return problems


def test_the_three_files_name_one_stable_release():
    problems = check({name: _read(name) for name in RELEASE_LINE_FILES})
    assert not problems, "\n".join(problems)


def _texts():
    return {name: _read(name) for name in RELEASE_LINE_FILES}


def _version(text):
    """The one version a file's download paths name (the suite's first test pins that)."""
    (version,) = set(DOWNLOAD_PATH_RE.findall(text))
    return version


def test_a_planted_callout_mismatch_is_caught():
    """Guards the check: the guide's callout one release behind the README."""
    texts = _texts()
    guide = texts["docs/USER_GUIDE.md"]
    version = _version(guide)
    texts["docs/USER_GUIDE.md"] = guide.replace(f"**v{version}**", "**v0.0.1**", 1)
    problems = check(texts)
    assert any("docs/USER_GUIDE.md" in p and "disagree" in p for p in problems), problems


def test_a_planted_asset_name_mismatch_is_caught():
    """One stale asset name in the front page, every other shape bumped."""
    texts = _texts()
    index = texts["docs/index.md"]
    version = _version(index)
    stale = index.replace(f"PyReconstruct-{version}-macOS-arm64.dmg", "PyReconstruct-0.0.1-macOS-arm64.dmg", 1)
    assert stale != index
    texts["docs/index.md"] = stale
    problems = check(texts)
    assert any("docs/index.md" in p and "asset names" in p for p in problems), problems


def test_a_planted_cross_file_mismatch_is_caught():
    """A whole file bumped on its own, consistent inside, stale against the rest."""
    texts = _texts()
    readme = texts["README.md"]
    version = _version(readme)
    texts["README.md"] = readme.replace(version, "0.0.1")
    problems = check(texts)
    assert any("different stable versions" in p for p in problems), problems


@pytest.mark.parametrize("asset", sorted(INSTALLERS_IN_EVERY_FILE))
def test_a_missing_installer_link_is_caught(asset):
    texts = _texts()
    guide = texts["docs/USER_GUIDE.md"]
    version = _version(guide)
    texts["docs/USER_GUIDE.md"] = guide.replace(f"PyReconstruct-{version}-{asset}", "PyReconstruct-x.y.z-nothing")
    problems = check(texts)
    assert any("does not link" in p and asset in p for p in problems), problems


def _destination(version, asset):
    return f"releases/download/v{version}/PyReconstruct-{version}-{asset}"


def test_a_typo_in_a_destination_alone_is_caught():
    """The label still reads arm64; only the file the link opens is wrong."""
    texts = _texts()
    guide = texts["docs/USER_GUIDE.md"]
    version = _version(guide)
    good = _destination(version, "macOS-arm64.dmg")
    assert guide.count(good) == 1
    texts["docs/USER_GUIDE.md"] = guide.replace(good, _destination(version, "macOS-arm65.dmg"))
    problems = check(texts)
    assert any("unknown release file" in p and "arm65" in p for p in problems), problems
    assert any("does not link" in p and "macOS-arm64.dmg" in p for p in problems), problems


def test_a_destination_swapped_for_another_asset_is_caught():
    """The label still names the Windows installer; the link opens the AppImage."""
    texts = _texts()
    index = texts["docs/index.md"]
    version = _version(index)
    windows = _destination(version, "Windows-x86_64-Setup.exe")
    assert index.count(windows) == 1
    texts["docs/index.md"] = index.replace(windows, _destination(version, "linux-x86_64.AppImage"))
    problems = check(texts)
    assert problems == ["docs/index.md: does not link ['Windows-x86_64-Setup.exe']"]

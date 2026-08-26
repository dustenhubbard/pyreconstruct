"""requirements.txt and pyproject.toml must pin the same versions.

Both files are live install paths: pyproject.toml drives uv and
``pip install .``, and ``launch/*/run.sh`` runs
``pip install -r requirements.txt`` on every startup. They are maintained by
hand, so they drift, and drift is silent -- a bumped pyproject looks like a
fixed CVE while the other file keeps shipping the vulnerable pin.

That is exactly what happened: the 2026-08-24 GitPython bump (3.1.57 to
3.1.58) reached pyproject.toml and uv.lock, requirements.txt kept 3.1.57,
and the alert came back on 2026-08-26. Dependabot could not catch it either
-- its uv entry watches pyproject.toml and uv.lock, not this file (it has a
pip entry for the root now).

An existing test in tests/test_export_svg_png.py checks that the export
packages are PRESENT in both files. This one checks the VERSIONS of
everything in both.
"""

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PIN = re.compile(r"^([A-Za-z0-9._-]+)==(\S+)")


def _requirements_pins():
    pins = {}
    for line in (REPO_ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = PIN.match(line)
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


def _pyproject_pins():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    pins = {}
    for spec in data["project"]["dependencies"]:
        m = PIN.match(spec.strip())
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


def test_no_pin_disagrees_between_the_two_files():
    """The guard the GitPython miss needed. A package pinned in both files
    must be pinned to the SAME version; a package in only one is fine (the
    presence rules live in test_export_svg_png.py)."""
    req, proj = _requirements_pins(), _pyproject_pins()
    drift = {
        name: (req[name], proj[name])
        for name in set(req) & set(proj)
        if req[name] != proj[name]
    }
    assert not drift, (
        "requirements.txt and pyproject.toml disagree on: "
        + ", ".join(
            f"{n} (requirements.txt {a}, pyproject.toml {b})"
            for n, (a, b) in sorted(drift.items())
        )
        + ". Both files are installed from, so the lower pin is what somebody "
        "actually gets; bump them together."
    )


def test_gitpython_is_at_or_above_the_patched_version():
    """The specific CVE set that opened this file (GHSA-4gmw-gg2m-w46p and
    five siblings): fixed in 3.1.58. Pinned rather than left to the drift
    check alone, so a matched pair at 3.1.57 in both files still fails."""
    from packaging.version import Version

    for label, pins in (
        ("requirements.txt", _requirements_pins()),
        ("pyproject.toml", _pyproject_pins()),
    ):
        pinned = pins.get("gitpython")
        assert pinned is not None, f"gitpython vanished from {label}"
        assert Version(pinned) >= Version("3.1.58"), (
            f"{label} pins gitpython {pinned}; 3.1.58 is the patched version"
        )


def test_dependabot_watches_every_manifest_we_install_from():
    """requirements.txt at the root went unwatched, which is why the drift
    survived. Pin the coverage: a pip entry for "/" and the uv entry for the
    pyproject side."""
    # Scanned with a regex rather than parsed: PyYAML is not a test
    # dependency, and the two keys this asserts on are one line each.
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text()
    entries = re.findall(
        r'package-ecosystem:\s*"?([\w-]+)"?.*?directory:\s*"?([^"\n]+)"?',
        text,
        re.S,
    )
    watched = {(eco, directory.strip()) for eco, directory in entries}
    assert ("pip", "/") in watched, (
        "no dependabot entry watches requirements.txt at the root; it drifted "
        "behind pyproject.toml for two days and kept a CVE alert open"
    )
    assert ("uv", "/") in watched

#!/usr/bin/env python3
"""Write a release's update-manifest.json and SHA256SUMS into its dist folder.

Usage:
    python3 release_update_files.py DIST --tag v1.24.0 --flavor stable

Run by the release job in .github/workflows/build-installers.yml after the
per-file ``.sha256`` files exist and before ``SHA256SUMS`` is signed.

``update-manifest.json`` is what the in-place updater will read: a schema
version, the tag, the version, the flavor, and one entry per platform. Every
entry is ``"inplace": {"enabled": false}``, and ``min_client`` is the
release's own version, which no installed client can be below and still be
updating to it. Both stay closed until the step that turns in-place updates
on opens them.

When DIST holds the Windows payload (scripts/build_update_payload.py writes
it, and the release job holds it back if its swap test failed), the Windows
entry also names the archive and its tree.json with their sizes, and gives
the installed size and file count, which the app needs for its free space
check. The hashes are in ``SHA256SUMS``, not repeated here.

A payload never costs the release its installers. Anything in DIST named
like a Windows payload that is not this release's pair, both halves present
and the tree.json for this release's version, flavor, and platform, is
deleted with its ``.sha256`` and a warning, before the manifest and
``SHA256SUMS`` are written. A payload from another build would be refused by
every client, and half of one is of no use to any.

``SHA256SUMS`` lists every file in DIST except the ``.sha256`` files, itself,
and its signature, in the format ``sha256sum`` writes and ``sha256sum -c``
reads, sorted by name byte for byte. The manifest is written first, so it is
listed too and the signature covers it.

Every name written here uses lowercase or no platform tokens, so clients from
1.23.0 and before, which take the first asset whose name contains
``Windows-x86_64`` or ``macOS-<arch>``, can never pick one as an installer
(tests/test_old_clients_never_pick_update_assets.py).
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from packaging.version import Version

from build_update_payload import app_name, payload_names

MANIFEST = "update-manifest.json"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.minisig"
SCHEMA = 1
FLAVORS = ("stable", "dev")
PLATFORMS = ("windows-x86_64", "macos-arm64", "macos-x86_64", "linux-x86_64")
# Any name build_update_payload.py could write for Windows, in any version or flavor,
# plus the .partial it writes first.
WINDOWS_PAYLOAD = re.compile(r"^PyReconstruct-.+-update-windows-", re.IGNORECASE)


def manifest(tag: str, flavor: str, dist: Path | None = None) -> dict:
    version = str(Version(tag[1:] if tag[:1] in "vV" else tag))
    platforms = {
        p: {"inplace": {"enabled": False}, "min_client": version}
        for p in PLATFORMS
    }
    if dist is not None:
        payload = windows_payload(dist, version, flavor)
        if payload:
            platforms["windows-x86_64"].update(payload)
    return {
        "schema": SCHEMA,
        "tag": tag,
        "version": version,
        "flavor": flavor,
        "platforms": platforms,
    }


def _drop(dist: Path, name: str, why: str) -> None:
    """Delete one payload file and its .sha256, so neither is published."""
    removed = False
    for path in (dist / name, dist / f"{name}.sha256"):
        if path.is_file():
            path.unlink()
            removed = True
    if removed:
        print(f"::warning::left {name} out of the release: {why}")


def windows_payload(dist: Path, version: str, flavor: str) -> dict | None:
    """The Windows entry's payload fields, or None when DIST holds no usable payload.

    Deletes every file named like a Windows payload that is not this release's
    whole, matching pair, so the manifest and SHA256SUMS never name it and it is
    never published.
    """
    archive_name, tree_name = payload_names(version, flavor)
    pair = (archive_name, tree_name)
    for path in sorted(dist.iterdir()):
        base = path.name[:-len(".sha256")] if path.name.endswith(".sha256") else path.name
        if path.is_file() and WINDOWS_PAYLOAD.match(base) and base not in pair:
            _drop(dist, base, f"it is not named for {version} ({flavor})")

    archive, tree_path = dist / archive_name, dist / tree_name
    if not archive.is_file() and not tree_path.is_file():
        return None
    problem = _tree_problem(archive, tree_path, version, flavor)
    if problem:
        for name in pair:
            _drop(dist, name, problem)
        return None
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    files = [e for e in tree["files"] if e.get("type", "file") == "file"]
    return {
        "payload": {"name": archive_name, "size": archive.stat().st_size},
        "tree": {"name": tree_name, "size": tree_path.stat().st_size},
        "installed_size": sum(e["size"] for e in files),
        "files": len(files),
    }


def _tree_problem(archive: Path, tree_path: Path, version: str, flavor: str) -> str | None:
    """Why this pair cannot ship, or None when it can."""
    if not archive.is_file() or not tree_path.is_file():
        return "it has no partner"
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except ValueError as e:
        return f"its tree.json is not valid JSON ({e})"
    if not isinstance(tree, dict):
        return "its tree.json is not an object"
    expected = {"version": version, "flavor": flavor, "app_name": app_name(flavor),
                "platform": "windows-x86_64"}
    for key, value in expected.items():
        if tree.get(key) != value:
            return f"its tree.json has {key} {tree.get(key)!r}, expected {value!r}"
    entries = tree.get("files")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return "its tree.json has no list of files"
    files = [e for e in entries if e.get("type", "file") == "file"]
    if not files:
        return "its tree.json lists no files"
    if not all(isinstance(e.get("size"), int) for e in files):
        return "its tree.json has a file with no size"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sums_lines(dist: Path) -> list[str]:
    names = sorted(
        (p.name for p in dist.iterdir()
         if p.is_file() and not p.name.endswith(".sha256") and p.name not in (SUMS, SIGNATURE)),
        key=lambda n: n.encode(),
    )
    return [f"{_sha256(dist / n)}  {n}\n" for n in names]


def write(dist: Path, tag: str, flavor: str) -> None:
    if flavor not in FLAVORS:
        raise SystemExit(f"unknown flavor {flavor!r}; expected one of {', '.join(FLAVORS)}")
    for stale in (SUMS, SIGNATURE):
        (dist / stale).unlink(missing_ok=True)
    (dist / MANIFEST).write_text(json.dumps(manifest(tag, flavor, dist), indent=2) + "\n", newline="\n")
    lines = sums_lines(dist)
    (dist / SUMS).write_text("".join(lines), newline="\n")
    sys.stdout.write("".join(lines))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dist", type=Path)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--flavor", required=True)
    args = ap.parse_args(argv)
    write(args.dist, args.tag, args.flavor)


if __name__ == "__main__":
    main()

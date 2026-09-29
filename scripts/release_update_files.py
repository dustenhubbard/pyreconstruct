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
check. The tree.json must be for this release's version, flavor, and
platform, or the script fails, since a payload from another build would be
refused by every client. The hashes are in ``SHA256SUMS``, not repeated here.

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


def windows_payload(dist: Path, version: str, flavor: str) -> dict | None:
    """The Windows entry's payload fields, or None when DIST has no payload."""
    archive_name, tree_name = payload_names(version, flavor)
    archive, tree_path = dist / archive_name, dist / tree_name
    if not archive.is_file() or not tree_path.is_file():
        for orphan in (archive, tree_path):
            if orphan.is_file():
                print(f"::warning::{orphan.name} has no partner; the manifest lists no Windows payload")
        return None
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"{tree_name} is not valid JSON: {e}")
    expected = {"version": version, "flavor": flavor, "app_name": app_name(flavor),
                "platform": "windows-x86_64"}
    for key, value in expected.items():
        if tree.get(key) != value:
            raise SystemExit(f"{tree_name} has {key} {tree.get(key)!r}, expected {value!r}")
    files = [e for e in tree.get("files", []) if e.get("type", "file") == "file"]
    if not files:
        raise SystemExit(f"{tree_name} lists no files")
    return {
        "payload": {"name": archive_name, "size": archive.stat().st_size},
        "tree": {"name": tree_name, "size": tree_path.stat().st_size},
        "installed_size": sum(e["size"] for e in files),
        "files": len(files),
    }


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

#!/usr/bin/env python3
"""Write a release's update-manifest.json and SHA256SUMS into its dist folder.

Usage:
    python3 release_update_files.py DIST --tag v1.24.0 --flavor stable

Run by the release job in .github/workflows/build-installers.yml after the
per-file ``.sha256`` files exist and before ``SHA256SUMS`` is signed.

``update-manifest.json`` is what the in-place updater will read: a schema
version, the tag, the version, the flavor, and one entry per platform. No
platform has an in-place payload yet, so every entry is
``"inplace": {"enabled": false}``, and ``min_client`` is the release's own
version, which no installed client can be below and still be updating to it.
Both stay closed until the step that ships the payloads opens them.

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

MANIFEST = "update-manifest.json"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.minisig"
SCHEMA = 1
FLAVORS = ("stable", "dev")
PLATFORMS = ("windows-x86_64", "macos-arm64", "macos-x86_64", "linux-x86_64")


def manifest(tag: str, flavor: str) -> dict:
    version = str(Version(tag[1:] if tag[:1] in "vV" else tag))
    return {
        "schema": SCHEMA,
        "tag": tag,
        "version": version,
        "flavor": flavor,
        "platforms": {
            p: {"inplace": {"enabled": False}, "min_client": version}
            for p in PLATFORMS
        },
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
    (dist / MANIFEST).write_text(json.dumps(manifest(tag, flavor), indent=2) + "\n", newline="\n")
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

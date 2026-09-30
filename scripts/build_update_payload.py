#!/usr/bin/env python3
"""Pack a frozen Windows build as its in-place update payload.

Usage:
    python scripts/build_update_payload.py "dist/PyReconstruct Dev" \
        --version 1.24.0.dev20260929 --flavor dev --out dist-assets

Run by the Windows leg of .github/workflows/build-installers.yml, after the
installer is built from the same folder. Writes two release assets into OUT:

    PyReconstruct-<ver>-update-windows-x86_64[-Dev].tar.xz
        The install folder's contents, with no top folder, in tree.json's
        order. An in-place update unpacks it into the staging folder's new/.
    PyReconstruct-<ver>-update-windows-x86_64[-Dev].tree.json
        Every file's path, size, sha256, and mode, and the version, flavor,
        app name, and platform. The helper checks every staged file against
        it before the swap.

The tree comes from ``build_tree`` in apply.py, the helper that later checks
it, and every path is held to the helper's own rules for a Windows tree, so a
release can never ship a tree the helper would refuse. The folder must hold
the app's program and the update helper in ``_updater``, or the version it
installs could not update itself in place.

Both names use a lowercase platform token, so no installer matcher, old or
new, takes them for an installer
(tests/test_old_clients_never_pick_update_assets.py).
"""

import argparse
import importlib.util
import json
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY_PY = ROOT / "PyReconstruct" / "modules" / "backend" / "updater" / "apply.py"

PLATFORM = "windows-x86_64"
FLAVORS = ("stable", "dev")
HELPER = "_updater/pyreconstruct-updater.exe"
XZ_PRESET = 6


def app_name(flavor: str) -> str:
    return "PyReconstruct Dev" if flavor == "dev" else "PyReconstruct"


def payload_names(version: str, flavor: str, platform: str = PLATFORM) -> tuple[str, str]:
    """(archive, tree) asset names for one release."""
    suffix = "-Dev" if flavor == "dev" else ""
    base = f"PyReconstruct-{version}-update-{platform}{suffix}"
    return f"{base}.tar.xz", f"{base}.tree.json"


def _apply():
    """apply.py by its path. It is stdlib only, so this needs nothing installed."""
    spec = importlib.util.spec_from_file_location("pyreconstruct_apply", APPLY_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(app_dir: Path, version: str, flavor: str, out: Path, mtime: int | None = None):
    """Write the archive and tree.json into ``out``. Returns (archive path, tree path, tree)."""
    if flavor not in FLAVORS:
        raise SystemExit(f"unknown flavor {flavor!r}; expected one of {', '.join(FLAVORS)}")
    name = app_name(flavor)
    app_dir = Path(app_dir)
    if app_dir.name != name:
        raise SystemExit(f"{app_dir} is not the {flavor} app; expected a folder named {name!r}")
    for required in (f"{name}.exe", HELPER):
        if not (app_dir / required).is_file():
            raise SystemExit(f"{app_dir} has no {required}")

    A = _apply()
    tree = A.build_tree(str(app_dir), version=version, flavor=flavor, app_name=name,
                        bundle_id=None, platform=PLATFORM)
    for entry in tree["files"]:
        try:
            A.safe_parts(entry["path"], windows=True)
        except A.Refused as e:
            raise SystemExit(f"the helper would refuse this tree: {e}")
        if entry.get("type", "file") not in ("file", "dir"):
            raise SystemExit(f"a Windows payload holds files and folders only: {entry['path']}")

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    archive_name, tree_name = payload_names(version, flavor)
    archive, tree_path = out / archive_name, out / tree_name
    stamp = int(time.time()) if mtime is None else int(mtime)

    # Both files are written as .partial and renamed only once both are whole.
    # On any failure neither name is left behind, so a release never holds a
    # half-written payload or half of a pair.
    partials = {path: path.with_name(path.name + ".partial") for path in (archive, tree_path)}
    try:
        with tarfile.open(partials[archive], "w:xz", preset=XZ_PRESET, format=tarfile.PAX_FORMAT) as tar:
            for entry in tree["files"]:
                info = tarfile.TarInfo(entry["path"])
                info.mtime = stamp
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                if entry.get("type") == "dir":
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tar.addfile(info)
                    continue
                info.size = entry["size"]
                info.mode = 0o755 if entry["mode"] & 0o111 else 0o644
                with open(app_dir.joinpath(*entry["path"].split("/")), "rb") as f:
                    tar.addfile(info, f)
        partials[tree_path].write_text(json.dumps(tree, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
        for final, partial in partials.items():
            os.replace(partial, final)
    except BaseException:
        for final, partial in partials.items():
            for path in (partial, final):
                if path.exists():
                    path.unlink()
        raise
    return archive, tree_path, tree


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("app_dir", type=Path, help="the frozen onedir folder, dist/<app name>")
    ap.add_argument("--version", required=True)
    ap.add_argument("--flavor", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    started = time.monotonic()
    archive, tree_path, tree = build(args.app_dir, args.version, args.flavor, args.out)
    files = [e for e in tree["files"] if e.get("type", "file") == "file"]
    installed = sum(e["size"] for e in files)
    sys.stdout.write(
        f"{archive.name}: {archive.stat().st_size} bytes\n"
        f"{tree_path.name}: {len(files)} files, {installed} bytes installed\n"
        f"packed in {time.monotonic() - started:.0f} s\n"
    )


if __name__ == "__main__":
    main()

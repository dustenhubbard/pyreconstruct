#!/usr/bin/env python3
"""Report a pull request that changes what a user sees without touching the docs.

The User Guide on main listed five wrong shortcuts (``Ctrl+M`` for merge
traces; the app binds ``Shift+M``) and left out nine newer keys. Every one of
those keys was changed or added by a reviewed pull request, and nothing asked
the author whether the guide still matched. This check asks.

The rule is narrow on purpose: a pull request that touches a user-facing path
(listed in ``USER_FACING`` below) should also change something under ``docs/``
or the top-level ``README.md``. Two ways out, both cheap:

  * change the docs in the same pull request, which is the normal way;
  * write an opt-out line in the pull request body and say why.

The opt-out is a body line rather than a label, for the same reasons as the
changelog check (``scripts/check_changelog_entry.py``): anyone who opened the
pull request can write one, and it carries a reason a reviewer can read. The
line is matched case-insensitively and needs text after the colon::

    No docs change: the dialog's layout moved, nothing it does changed

The path list is short on purpose. A file goes on it when changing it usually
changes a menu, a dialog, a tool, a shortcut, the updater or the installer. The
field widget's mouse and paint code is left off: it changes often, and most of
those changes are invisible. A false alarm costs one body line; a list that
fires on every refactor teaches people to paste the line without reading.

The job also lists stale-shot candidates: guide images that show a file the
pull request touched. The map from each image to the files it shows lives in
``docs/assets/images/user-guide/sources.json``. That file may not exist yet;
when it is missing, the list is skipped and the output says so. The list is
advice for the reviewer and never fails the check, even when ``BLOCKING`` is on.

REPORT-ONLY. ``BLOCKING = False`` below means this script exits 0 whatever it
finds, and the finding arrives as a warning annotation and a job summary. Set
``BLOCKING = True`` to make it a gate; nothing in the workflow needs to change.
A gate also needs ``docs-entry`` added to the required checks in branch
protection, which is a settings change, not a file change.

Usage::

    check_docs_entry.py --changed-files FILE --body FILE [--shot-sources FILE]

``--changed-files`` is a newline-separated list of repository-relative paths.
``--body`` is the pull request body. ``--shot-sources`` is the image map; a path
that does not exist is allowed. Stdlib only, so this runs with no project
environment at all.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Flip to True to make this a gate. This is the only line that needs to change:
# it switches the exit code from 0 to 1 on a finding, and the GitHub annotation
# from `warning` to `error`. The stale-shot list stays a notice either way.
BLOCKING = False

_MODULES = "PyReconstruct/modules/"

# A path ending in "/" covers everything under it; any other path is one file.
USER_FACING = (
    _MODULES + "gui/main/menubar.py",
    _MODULES + "gui/main/mac_menubar.py",
    _MODULES + "gui/main/context_menu_list.py",
    _MODULES + "gui/dialog/",
    _MODULES + "gui/palette/",
    _MODULES + "gui/popup/",
    _MODULES + "datatypes/default_settings.py",
    _MODULES + "backend/updater/",
    "packaging/linux/install.sh",
    "packaging/linux/install-appimage.sh",
    "packaging/linux/uninstall.sh",
    "packaging/windows/PyReconstruct.iss",
    "packaging/macos/first-launch.html",
    "packaging/macos/dmg_settings.py",
)

DOCS_PREFIX = "docs/"
README = "README.md"

SHOT_SOURCES = "docs/assets/images/user-guide/sources.json"

# `No docs change: <reason>`, optionally as a markdown list item, anywhere in
# the body. A reason is required: a bare marker with nothing after the colon is
# a checkbox, not a decision, and does not count.
OPT_OUT_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?no[ \t]+docs[ \t]+change[ \t]*:[ \t]*(\S.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

OPT_OUT_EXAMPLE = "No docs change: <why the docs still match the app>"


def _matches(path, entry):
    """Whether ``path`` is the file ``entry`` names, or under the folder it names."""
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry


def user_facing_files(changed_files):
    """The changed files that are on the user-facing list, sorted."""
    return sorted(
        f for f in changed_files if any(_matches(f, entry) for entry in USER_FACING)
    )


def evaluate(changed_files, pr_body):
    """Decide whether this change needs a docs change it does not have.

    Returns ``(status, detail)``. ``status`` is one of:

      ``no-ui-change``  no user-facing path changed
      ``recorded``      a file under ``docs/`` or ``README.md`` is in the change,
                        and ``detail`` names the first one
      ``opted-out``     the body carries the opt-out line; detail is the reason
      ``missing``       the finding
    """
    files = [f.strip() for f in changed_files if f and f.strip()]

    if not user_facing_files(files):
        return "no-ui-change", ""

    docs = sorted(f for f in files if f.startswith(DOCS_PREFIX) or f == README)
    if docs:
        return "recorded", docs[0]

    match = OPT_OUT_RE.search(pr_body or "")
    if match:
        return "opted-out", match.group(1).strip()

    return "missing", ""


def load_shot_sources(path):
    """The image map, or ``None`` when the file does not exist yet.

    The map is a JSON object: each key is an image path relative to the
    repository root, each value a list of source paths it shows (a path ending
    in "/" covers a folder). Anything else is an error, not a silent skip: a
    broken map would hide every stale shot.
    """
    if path is None or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str)
        and isinstance(v, list)
        and all(isinstance(s, str) for s in v)
        for k, v in data.items()
    ):
        raise ValueError(f"{path}: expected an object of image path to list of paths")
    return data


def stale_shots(changed_files, shot_sources):
    """Guide images that show a changed file and are not changed themselves.

    Returns a sorted list of ``(image, [changed sources])``. An image the pull
    request also changes has been reshot, so it is left out.
    """
    files = {f.strip() for f in changed_files if f and f.strip()}
    found = []
    for image, sources in sorted(shot_sources.items()):
        if image in files:
            continue
        hits = sorted(f for f in files if any(_matches(f, s) for s in sources))
        if hits:
            found.append((image, hits))
    return found


def _message(changed_files):
    """The finding, written so the fix takes seconds and needs nothing read."""
    ui_files = user_facing_files(f.strip() for f in changed_files if f.strip())
    shown = ui_files[:5]
    more = len(ui_files) - len(shown)
    lines = [
        f"This changes {len(ui_files)} user-facing file(s) and changes nothing "
        f"under {DOCS_PREFIX} or {README}.",
        "",
        "User-facing files changed:",
    ]
    lines += [f"  {f}" for f in shown]
    if more:
        lines.append(f"  ... and {more} more")
    lines += [
        "",
        "Update the User Guide section for that screen in docs/USER_GUIDE.md "
        f"(or {README}, if that is where it is described) in this pull request.",
        "",
        "Or, if the docs still match the app, put this line in the pull request "
        "body:",
        f"  {OPT_OUT_EXAMPLE}",
    ]
    return "\n".join(lines)


def _shots_message(found):
    lines = ["These guide images show a file this pull request changes:"]
    for image, hits in found:
        lines.append(f"  {image}")
        lines += [f"    shows {h}" for h in hits]
    lines += [
        "",
        "Reshoot each one in this pull request, or say in the body why it "
        "still matches.",
    ]
    return "\n".join(lines)


def _escape(text):
    """Escape text for a GitHub workflow command, so it stays one command."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit(level, title, body):
    """A GitHub annotation plus a job summary, and the same text on stdout."""
    print(f"{title}\n\n{body}\n")
    print(f"::{level} title={_escape(title)}::{_escape(body)}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n```\n{body}\n```\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", required=True, type=Path)
    parser.add_argument("--body", required=True, type=Path)
    parser.add_argument("--shot-sources", type=Path, default=None)
    args = parser.parse_args(argv)

    changed_files = args.changed_files.read_text(encoding="utf-8").splitlines()
    pr_body = args.body.read_text(encoding="utf-8") if args.body.exists() else ""

    status, detail = evaluate(changed_files, pr_body)

    shot_sources = load_shot_sources(args.shot_sources)
    if shot_sources is None:
        if args.shot_sources is not None:
            print(f"stale-shot list: skipped ({args.shot_sources} does not exist yet)")
    else:
        found = stale_shots(changed_files, shot_sources)
        if found:
            _emit("notice", "Guide images that may be stale", _shots_message(found))
        else:
            print("stale-shot list: no guide image shows a changed file")

    if status == "missing":
        level = "error" if BLOCKING else "warning"
        title = (
            "Missing docs change"
            if BLOCKING
            else "Missing docs change (report-only, not blocking)"
        )
        _emit(level, title, _message(changed_files))
        return 1 if BLOCKING else 0

    explanation = {
        "no-ui-change": "no user-facing file changed",
        "recorded": f"{detail} is part of this change",
        "opted-out": f"opted out in the pull request body: {detail}",
    }[status]
    print(f"docs check: ok ({explanation})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

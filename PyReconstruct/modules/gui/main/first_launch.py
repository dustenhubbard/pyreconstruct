"""First-launch / version-aware startup helpers.

Pure logic for two startup conveniences, deliberately free of Qt *widgets* so it
can be unit-tested headlessly:

* silent username resolution (never prompts on launch), and
* the "What's new" version-seen gate plus CHANGELOG note extraction.

The GUI shells that call these live in ``main_window`` (startup wiring) and
``gui.dialog.whats_new`` (the dialog).
"""

import re
from pathlib import Path

from packaging.version import Version, InvalidVersion

from PyReconstruct.modules.datatypes.default_settings import get_username
from PyReconstruct.modules.constants.locations import assets_dir, src_dir
from PyReconstruct.modules.backend.updater.updater import GITHUB_REPO

WHATSNEW_KEY = "last_whatsnew_version"


# --- username ----------------------------------------------------------------
def resolve_username(settings, series=None, default_factory=get_username):
    """Resolve the tracking username silently -- never prompts.

    Uses a name already saved on this machine; otherwise falls back to the OS
    login (the documented default) and persists it so it is stable across runs.
    Sets ``series.user`` when a series is given so trace-history attribution
    still has a name.

        Params:
            settings: a QSettings-like object (``value``/``setValue``).
            series: the open series whose ``user`` should be set (optional).
            default_factory: callable returning the fallback name.

        Returns:
            (str) the resolved username.
    """
    name = settings.value("username")
    if not (isinstance(name, str) and name.strip()):
        name = (default_factory() or "").strip() or "default"
        settings.setValue("username", name)
    if series is not None:
        series.user = name
    return name


# --- what's-new version gate --------------------------------------------------
def _safe_version(s):
    """Parse ``s`` as a version, or None if it is missing/unparseable."""
    if not s or not isinstance(s, str):
        return None
    try:
        return Version(s)
    except InvalidVersion:
        return None


def whats_new_due(stored, current):
    """True when the What's-new dialog should show for ``current``.

    Fresh install (no stored value) or an upgrade (stored < current) -> show.
    Re-launch of a seen version, a downgrade, or an indeterminate ``current``
    version -> don't. A corrupt stored value shows once and then self-heals.
    """
    cur = _safe_version(current)
    if cur is None:
        return False
    if not stored:
        return True
    prev = _safe_version(stored)
    if prev is None:
        return True
    return prev < cur


# --- changelog notes ----------------------------------------------------------
def find_changelog_path():
    """Locate the bundled ``CHANGELOG.md`` across source and frozen layouts."""
    candidates = [
        Path(assets_dir) / "CHANGELOG.md",       # frozen build (bundled in assets)
        Path(src_dir).parent / "CHANGELOG.md",   # source checkout (repo root)
        Path(src_dir) / "CHANGELOG.md",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def find_whats_new_path():
    """Locate the bundled ``WHATS_NEW.md`` (friendly highlights) across layouts."""
    candidates = [
        Path(assets_dir) / "WHATS_NEW.md",       # frozen build (bundled in assets)
        Path(src_dir).parent / "WHATS_NEW.md",   # source checkout (repo root)
        Path(src_dir) / "WHATS_NEW.md",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def _normalize_version(version):
    v = (version or "").strip()
    return v[1:] if v[:1] in ("v", "V") else v


def parse_changelog_section(text, version):
    """Return the markdown body of a CHANGELOG section, or None.

    Matches a Keep-a-Changelog heading like ``## [1.20.2] - 2026-...`` (or
    ``## [Unreleased]``) and returns everything up to the next ``## `` heading.
    Version matching ignores a leading ``v`` on either side.
    """
    if not text:
        return None
    target = _normalize_version(version)
    if not target:
        return None
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+\[([^\]]+)\]", line)
        if m and _normalize_version(m.group(1)).lower() == target.lower():
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if re.match(r"^##\s+\[", line):
            break
        body.append(line)
    section = "\n".join(body).strip()
    return section or None


def github_release_url(version=None):
    """Releases page (or a specific tag) on the repo the updater serves."""
    base = f"https://github.com/{GITHUB_REPO}/releases"
    v = _normalize_version(version)
    return f"{base}/tag/v{v}" if v and _safe_version(v) else base


def release_notes_markdown(version):
    """Friendly, user-facing highlights for ``version`` (offline-safe).

    Shows the version's section from ``WHATS_NEW.md`` -- short, plain-language
    highlights, deliberately *not* the technical CHANGELOG. If no highlights are
    bundled for this version, returns a brief, non-technical message; the detailed
    changelog is reached via the "Full release notes on GitHub" link, not here.
    Never raises and never touches the network.
    """
    path = find_whats_new_path()
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = None
        if text:
            section = parse_changelog_section(text, version)
            if section:
                return section
    return (
        "Thanks for updating PyReconstruct.\n\n"
        "Click **Full release notes on GitHub** below to see everything that "
        "changed in this version."
    )

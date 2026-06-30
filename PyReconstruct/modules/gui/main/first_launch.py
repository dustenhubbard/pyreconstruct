"""First-launch / version-aware startup helpers.

Pure logic for two startup conveniences, deliberately free of Qt *widgets* so it
can be unit-tested headlessly:

* silent username resolution (never prompts on launch), and
* the "What's new" version-seen gate plus the per-version notes builder (the
  friendly highlights come from ``WHATS_NEW.md``, not the technical CHANGELOG).

The GUI shells that call these live in ``main_window`` (startup wiring) and
``gui.dialog.whats_new`` (the dialog).
"""

import re
from datetime import datetime
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


# Keep-a-Changelog heading: ``## [<version>] — <date>`` (date optional). The
# separator may be a hyphen or an en/em dash; trailing text after ``]`` is the
# date when present.
_HEADING_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*(.*?)\s*$")


def _parse_heading(line):
    """Parse a section heading into ``(version, date_or_None)``, or None.

    ``version`` is the text inside ``[...]``; ``date`` is whatever follows the
    leading dash separator (or None when the heading carries no date).
    """
    m = _HEADING_RE.match(line)
    if not m:
        return None
    version = m.group(1).strip()
    tail = m.group(2).strip()
    date = None
    if tail:
        date = tail.lstrip("-–—").strip() or None
    return version, date


def parse_all_sections(text):
    """Parse every version section of the notes in file order.

    Returns an ordered list of ``{"version", "date", "body"}`` dicts. The file is
    maintained newest-first, so the list is too. ``date`` is the raw heading date
    (or None); ``body`` is the markdown between this heading and the next.
    """
    if not text:
        return []
    sections = []
    version = date = None
    body = []
    for line in text.splitlines():
        parsed = _parse_heading(line)
        if parsed is not None:
            if version is not None:
                sections.append(
                    {"version": version, "date": date, "body": "\n".join(body).strip()}
                )
            version, date = parsed
            body = []
        elif version is not None:
            body.append(line)
    if version is not None:
        sections.append(
            {"version": version, "date": date, "body": "\n".join(body).strip()}
        )
    return sections


def friendly_date(date_str):
    """Format an ISO date (``2026-06-29``) as ``June 29, 2026``.

    Returns the input unchanged when it is missing or not a parseable ISO date
    (cross-platform: avoids the non-portable ``%-d`` directive).
    """
    if not date_str or not isinstance(date_str, str):
        return date_str
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return date_str
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def parse_changelog_section(text, version):
    """Return the markdown body of a single version's section, or None.

    Matches a Keep-a-Changelog heading like ``## [1.20.2] — 2026-06-29`` (or
    ``## [Unreleased]``). Version matching ignores a leading ``v`` on either side.
    """
    target = _normalize_version(version)
    if not text or not target:
        return None
    for section in parse_all_sections(text):
        if _normalize_version(section["version"]).lower() == target.lower():
            return section["body"] or None
    return None


def github_release_url(version=None):
    """Releases page (or a specific tag) on the repo the updater serves."""
    base = f"https://github.com/{GITHUB_REPO}/releases"
    v = _normalize_version(version)
    return f"{base}/tag/v{v}" if v and _safe_version(v) else base


# Shown when the running version has no friendly highlights bundled at all; the
# detailed changelog is reached via the "Full release notes on GitHub" link.
GENERIC_NOTES = (
    "Thanks for updating PyReconstruct.\n\n"
    "Click **Full release notes on GitHub** below to see everything that "
    "changed in this version."
)


def _read_whats_new():
    """Read the bundled ``WHATS_NEW.md``, or ``""`` if missing (never raises)."""
    path = find_whats_new_path()
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _render_sections(sections, truncated):
    """Render selected sections as ``### <version> — <friendly date>`` + bullets."""
    blocks = []
    for s in sections:
        date = friendly_date(s["date"]) if s["date"] else None
        heading = f"### {s['version']} — {date}" if date else f"### {s['version']}"
        blocks.append(f"{heading}\n\n{s['body']}" if s["body"] else heading)
    body = "\n\n".join(blocks).strip()
    if truncated:
        body += "\n\n_…and earlier releases — see the full notes on GitHub._"
    return body


def whats_new_content(current, last_seen=None, cap=5, text=None):
    """Build what the What's-new dialog renders (offline-safe, never raises).

    Returns a dict:
      * ``version``   -- the current version string, as given.
      * ``date``      -- friendly release date of the current version, or None.
      * ``orienter``  -- "What's new since <last_seen>" across an update, else
                         "Welcome to PyReconstruct" on a fresh install.
      * ``body``      -- markdown: each shown section as ``### <version> —
                         <friendly date>`` plus its bullets, newest first. Falls
                         back to a friendly generic note when the running version
                         has no section at all.
      * ``truncated`` -- True when more than ``cap`` missed sections existed.

    Sections shown: when ``last_seen`` is a valid version older than ``current``,
    every section with ``last_seen < version <= current`` (newest first, capped at
    ``cap``); on a fresh install (no/older/invalid ``last_seen``) the recent
    release history -- the current version plus the few before it, newest first,
    capped at ``cap``. ``text`` overrides the
    bundled notes (for testing); by default the bundled ``WHATS_NEW.md`` is read.
    """
    if text is None:
        text = _read_whats_new()
    sections = parse_all_sections(text)

    cur_norm = _normalize_version(current)
    cur_v = _safe_version(current)
    prev_v = _safe_version(last_seen)
    updating = prev_v is not None and cur_v is not None and prev_v < cur_v

    orienter = f"What's new since {last_seen}" if updating else "Welcome to PyReconstruct"

    current_section = next(
        (s for s in sections
         if cur_norm and _normalize_version(s["version"]).lower() == cur_norm.lower()),
        None,
    )
    friendly = (
        friendly_date(current_section["date"])
        if current_section and current_section["date"] else None
    )

    # No notes for the running version at all -> friendly generic body.
    if current_section is None:
        return {"version": current, "date": friendly, "orienter": orienter,
                "body": GENERIC_NOTES, "truncated": False}

    truncated = False
    if updating:
        shown = [
            s for s in sections
            if _safe_version(s["version"]) is not None
            and prev_v < _safe_version(s["version"]) <= cur_v
        ]
        shown.sort(key=lambda s: _safe_version(s["version"]), reverse=True)
        if len(shown) > cap:
            shown, truncated = shown[:cap], True
    else:
        # Fresh install: welcome the user with the recent release history (the
        # current version plus the few before it), newest first and capped -- so a
        # newcomer sees what recent releases brought, not just the version they
        # happened to install.
        shown = sorted(
            (s for s in sections
             if _safe_version(s["version"]) is not None
             and (cur_v is None or _safe_version(s["version"]) <= cur_v)),
            key=lambda s: _safe_version(s["version"]), reverse=True,
        )
        if len(shown) > cap:
            shown, truncated = shown[:cap], True

    return {"version": current, "date": friendly, "orienter": orienter,
            "body": _render_sections(shown, truncated), "truncated": truncated}

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
from PyReconstruct.modules.backend.updater.install_info import install_kind

WHATSNEW_KEY = "last_whatsnew_version"

# The "never show the popup" preference, stored beside WHATSNEW_KEY in the same
# QSettings store so the two mechanisms that write it (the dialog's "Don't show
# again" button and the Help-menu toggle) cannot disagree about where it lives.
# It suppresses only the unasked startup popup; Help > What's new stays an
# explicit request and always opens. While suppressed, WHATSNEW_KEY is not
# advanced, so switching the popup back on makes it eligible again under the
# ordinary once-per-version rules: any release missed while it was off shows on
# the next launch.
WHATSNEW_SUPPRESS_KEY = "suppress_whatsnew"

# The popup ships on: with nothing stored, the stable app shows the notes once
# after an update (his call, 2026-10-07; it shipped off from 2026-08-21 to
# here, when the stable build was meant to stay quiet). The toggle and the
# dialog's "Don't show again" button keep working either way; this is only
# what an unset preference means. A dev build never shows it regardless; see
# ``whats_new_due``.
WHATSNEW_SUPPRESS_DEFAULT = False

# Marker recording that ``reset_whats_new_popup_once`` has run in this store.
# Per app, beside the two keys it governs; a plain key rather than ``meta/``,
# following ``update_check_on_startup_default_applied``, so somebody reading
# their own settings can see what happened. Mirrored as a literal in
# constants/settings_domain.py (PER_APP_KEYS); the test on that list checks
# the two stay in step.
WHATSNEW_RESET_MARKER = "whatsnew_popup_reset_applied"

# Keys a store holds only if PyReconstruct has launched from it before.
# ``username`` is persisted by the first read of it, on every launch since the
# option existed; the update-check marker has been written on every launch
# since 1.21.0. Both are shared keys, so they are read from the shared store.
# ``allKeys()`` is deliberately not used: on macOS it also lists the global
# NSUserDefaults domain, so a fresh store never reads as empty through it.
PRIOR_INSTALL_KEYS = ("username", "update_check_on_startup_default_applied")


def whats_new_suppressed(stored):
    """True when the stored preference says never to show the popup.

    QSettings round-trips a Python bool through backends that hand back the
    strings "true"/"false" (the INI format among them), so the string
    spellings count as well as real booleans. Anything unrecognized reads as
    not suppressed: the popup is the documented default, and a corrupt value
    must not silently switch it off.
    """
    if isinstance(stored, str):
        return stored.strip().lower() in ("true", "1", "yes")
    return bool(stored)

# How many releases the Help-menu re-open lists, as opposed to the default
# ``cap`` the post-update path uses.
#
# The two paths want different amounts. Across an update the dialog is showing
# what the reader missed, and the range between their last-seen version and this
# one is however long it is. On the Help menu nobody missed anything: they went
# looking for the notes for the version they are running. Renders of the shipped
# 1.21.0-beta-7 notes: the post-update body is 15,816 characters, and the
# on-demand body at the default cap of five was 23,456 -- a scroll long enough
# that the release they opened it for is the only part most readers ever see.
#
# Three releases, chosen 2026-08-25: enough recent history that a reader sees
# what the last few updates brought, short enough that the release they opened
# it for stays the first thing on screen. The builder marks a capped body
# ``truncated``, which appends the line pointing at the full notes on GitHub,
# and the dialog carries that link of its own besides. Nothing becomes
# unreachable; it stops being pre-expanded.
ON_DEMAND_CAP = 3

# Provenance line shown below the notes in every framing of the What's-new dialog,
# and near the footer of the GitHub release body. Maintainer-approved verbatim: it
# names who maintains this build without naming any other repository, so a lab that
# installs it knows whose build it is and reports its issues to the right person.
# It is a quiet provenance line, not a boast; keep it a distinct field so it reads
# as an aside below the notes rather than as one more release bullet.
MAINTAINER_BYLINE = "An independent build of PyReconstruct, maintained by Dusten Hubbard."

# Where the byline points, and which word carries the link. The project name
# inside the provenance line is a link to the home page, so a lab that wants to
# know whose build this is can get there from the dialog rather than searching
# for it. The name appears in MAINTAINER_BYLINE exactly once; only that first
# occurrence is linked.
HOMEPAGE_URL = "https://pyreconstruct.org"
LINKED_NAME = "PyReconstruct"


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

    A dev release never shows it: a nightly (``1.24.0.dev20260928``) or a
    source install of main (``1.23.1.dev5+g...``) runs ahead of the notes,
    which are written for the stable it previews, and a build that changes
    every day would otherwise ask every day. Nothing is recorded either, so
    the stable that follows still gets its one showing.
    """
    cur = _safe_version(current)
    if cur is None or cur.is_devrelease:
        return False
    if not stored:
        return True
    prev = _safe_version(stored)
    if prev is None:
        return True
    return prev < cur


def reset_whats_new_popup_once(settings, current, shared=None):
    """Bring the popup back on for everyone, once, and keep a fresh install quiet.

    The popup shipped off by default from 2026-08-21 until this version, and
    the Help toggle and the "Don't show again" button wrote ``suppress_whatsnew``
    all that while. His call on turning it back on (2026-10-07): a user's own
    choice to turn it off is respected only from this version on, so a value
    stored before this version does not bind, and a fresh install does not
    show the notes at all. ``maybe_show_whats_new`` cannot tell an old "off"
    from a new one and cannot tell a fresh install from an upgrade on a store
    that never showed the popup, so this runs first and settles both, at the
    first launch of the first version that carries it:

    * **marker present**: nothing, whatever is stored. Every write of
      ``suppress_whatsnew`` after this point is a decision and is kept.
    * **fresh install**: no last-seen version, and none of
      ``PRIOR_INSTALL_KEYS`` in ``shared``. The running version is recorded
      as seen, so the first popup this install ever shows is the update after
      it. Recorded only when the popup would otherwise be due: a dev build
      records nothing, the same as its gate.
    * **anything else**: an upgrade. The stored suppression is removed, so the
      ordinary once-per-version rules show the notes once on this launch, and
      the user can switch the popup off again from the dialog or the Help menu.

    The marker is written last, so a write that fails leaves the reset to run
    again next launch rather than recording it as done. Never writes
    ``suppress_whatsnew`` itself: the default carries the "on", and a stored
    ``False`` would be indistinguishable from a user's choice.

    ``settings`` is the store holding the What's new keys (this app's own);
    ``shared`` is where the prior-install evidence lives, and defaults to
    ``settings`` because for the stable app the two are one store. Both take
    anything QSettings-shaped (``contains``/``value``/``setValue``/``remove``).
    Returns True when the reset ran, whether or not it changed anything.
    """
    if settings.contains(WHATSNEW_RESET_MARKER):
        return False
    if shared is None:
        shared = settings
    fresh = (
        not settings.contains(WHATSNEW_KEY)
        and not any(shared.contains(key) for key in PRIOR_INSTALL_KEYS)
    )
    if fresh:
        if whats_new_due(None, current):
            settings.setValue(WHATSNEW_KEY, current)
    else:
        settings.remove(WHATSNEW_SUPPRESS_KEY)
    settings.setValue(WHATSNEW_RESET_MARKER, True)
    return True


def reset_whats_new_popup_startup(current=None):
    """Run ``reset_whats_new_popup_once`` against the real stores, at launch.

    Called from ``run.py`` before the ``QApplication`` exists, beside the
    settings fold: the fresh-install test reads keys that ``MainWindow``
    writes while it is being built (``username`` through the welcome series,
    the update-check marker through its own migration), so this has to look
    before any of that runs. Resolves both domains through ``domain_for`` so
    the Dev app resets its own popup state and reads the shared store for
    the evidence. Never raises: a settings correction on the startup path
    must not be able to stop PyReconstruct from opening, and an unrecorded
    reset simply runs again next launch. ``current`` is injectable for tests.
    """
    try:
        from PySide6.QtCore import QSettings
        from PyReconstruct.modules.constants.settings_domain import domain_for
        from PyReconstruct.modules.backend.updater.install_info import (
            current_version_str,
        )
        if current is None:
            current = current_version_str()
        settings = QSettings(*domain_for(
            WHATSNEW_KEY, WHATSNEW_SUPPRESS_KEY, WHATSNEW_RESET_MARKER,
        ))
        shared = QSettings(*domain_for(*PRIOR_INSTALL_KEYS))
        ran = reset_whats_new_popup_once(settings, current, shared=shared)
        if ran:
            settings.sync()
        return ran
    except Exception:
        return False


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
    # Match by parsed PEP 440 version so any equivalent spelling of the header
    # lines up with the runtime version -- e.g. a [1.21.0-beta-1] header (which
    # setuptools-scm bakes into the app as 1.21.0b1) matches a 1.21.0b1 runtime;
    # fall back to a normalized string compare for non-version headers
    # ([Unreleased]). Mirrors whats_new_content's matching.
    target_v = _safe_version(target)
    for section in parse_all_sections(text):
        sv = section["version"]
        if target_v is not None and _safe_version(sv) == target_v:
            return section["body"] or None
        if _normalize_version(sv).lower() == target.lower():
            return section["body"] or None
    return None


def github_release_url(version=None):
    """Releases page (or a specific tag) on the repo the updater serves."""
    base = f"https://github.com/{GITHUB_REPO}/releases"
    v = _normalize_version(version)
    return f"{base}/tag/v{v}" if v and _safe_version(v) else base


# Shown when the running version has no friendly highlights bundled at all; the
# detailed changelog is reached via the "All release notes on GitHub" link.
GENERIC_NOTES = (
    "Thanks for updating PyReconstruct.\n\n"
    "Click **All release notes on GitHub** below to see everything that "
    "changed in this version."
)

# The same fallback under the welcome framing, where thanking the reader for
# updating addresses the wrong person: nobody updated, this is a first run.
GENERIC_WELCOME_NOTES = (
    "Welcome to PyReconstruct.\n\n"
    "Click **All release notes on GitHub** below to see what is in this "
    "version."
)


# Appended to the welcome framing only -- the one showing that greets someone
# who has never run PyReconstruct before. The app checks for updates on its own,
# the switch for that lives in the Help menu, and the nightly build is a second
# app (PyReconstruct Dev) rather than a channel this one can switch to. Nothing
# else points a newcomer at any of that, so saying it here is the honest moment:
# it is the first thing the app says to them.
#
# Deliberately not shown across an update -- someone updating already knows the
# check exists, having just used it -- nor on the Help-menu re-open, where the
# reader went looking for the notes rather than needing to be oriented. Nor on
# an install that does not run the check at all; see ``_is_installed_app``.
_UPDATE_CHECK_SENTENCES = (
    "PyReconstruct checks once a day for a new version and tells you when one "
    "is out. You can turn this off under Help ▸ Automatically check for "
    "updates. "
)

# The stable app's note. Kept under this name for anything that imports it; the
# dialog itself goes through ``welcome_update_note()`` so the Dev app gets its
# own last two sentences.
WELCOME_UPDATE_NOTE = _UPDATE_CHECK_SENTENCES + (
    "PyReconstruct Dev is the nightly build. It installs beside this app, and "
    "the Help menu has a link to download it."
)

WELCOME_UPDATE_NOTE_DEV = _UPDATE_CHECK_SENTENCES + (
    "This is the nightly build. PyReconstruct, the stable app, installs beside "
    "it, and the Help menu has a link to download it."
)


def welcome_update_note():
    """The update-checks note for THIS build, decided when the dialog opens.

    Reads ``app_display_name`` at call time, the way the other flavored helpers
    do (``updater.pinned_channel``, ``menubar._other_flavor_label``), so a test
    can flip the flavor without reloading the module.
    """
    from PyReconstruct.modules.datatypes.series_owner import app_display_name
    if "Dev" in app_display_name():
        return WELCOME_UPDATE_NOTE_DEV
    return WELCOME_UPDATE_NOTE


def _is_installed_app():
    """True in the installed app, the only place that checks for updates.

    ``MainWindow.checkForUpdatesStartup`` returns early unless the install
    kind is ``"frozen"``, ``"appimage"`` or ``"linux-installer"``, so when
    running from source the note would be describing something that does not
    happen. Compares against those values rather than testing for "not
    source", so a kind added later is excluded until someone decides
    otherwise: ``install_kind`` answers ``"source"`` for a git checkout and a
    pip install alike, and that set can grow.

    Reads the module-level ``install_kind`` so a test can rebind it, the way the
    other collaborators in this module are rebound. Never raises: a first-launch
    convenience must not be able to break the dialog.
    """
    try:
        return install_kind() in ("frozen", "appimage", "linux-installer")
    except Exception:
        return False


def _with_welcome_note(body):
    """Append the update-checks note to a welcome body, set off by a rule.

    The rule and the trailing paragraph are both conventions the notes already
    use (``WHATS_NEW.md`` separates its own blocks with ``---``, and the
    truncation hint is a paragraph after the bullets), so the note reads as an
    aside rather than as another release bullet. Works on either body the
    builder can produce: the rendered release history, or the generic fallback
    shown when the running version has no section bundled -- a first-run reader
    on such a build is exactly who most needs the orienting.
    """
    note = welcome_update_note()
    if not body:
        return note
    return f"{body}\n\n---\n\n{note}"


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
        # Asterisk emphasis, not underscores: Qt's markdown renderer follows
        # the GitHub dialect, where _single underscores_ draw as UNDERLINE.
        # This aside rendered as one long not-a-link until 2026-08-25.
        body += "\n\n*…and earlier releases: see the full notes on GitHub.*"
    return body


def whats_new_content(current, last_seen=None, cap=3, text=None, on_demand=False,
                      installed_app=None):
    """Build what the What's-new dialog renders (offline-safe, never raises).

    Returns a dict:
      * ``version``   -- the current version string, as given.
      * ``date``      -- friendly release date of the current version, or None.
      * ``orienter``  -- "What's new since <last_seen>" across an update,
                         "Welcome to PyReconstruct" on a fresh install, or
                         "Recent releases" for an on-demand re-open.
      * ``body``      -- markdown: each shown section as ``### <version> —
                         <friendly date>`` plus its bullets, newest first. Falls
                         back to a friendly generic note when the running version
                         has no section at all, which under the welcome framing
                         greets rather than thanks. In the installed app under
                         the welcome framing, and only there,
                         ``welcome_update_note()`` is appended to whichever of
                         those two bodies was built.
      * ``byline``    -- the maintainer provenance line (``MAINTAINER_BYLINE``),
                         the same on every framing; the dialog renders it once,
                         in the footer row below the body.
      * ``truncated`` -- True when more than ``cap`` missed sections existed.

    Sections shown: when ``last_seen`` is a valid version older than ``current``,
    every section with ``last_seen < version <= current`` (newest first, capped at
    ``cap``); on a fresh install (no/older/invalid ``last_seen``) the recent
    release history -- the current version plus the few before it, newest first,
    capped at ``cap``. ``on_demand`` (the Help-menu re-open) always shows that
    recent release history regardless of ``last_seen``, since a returning user is
    browsing rather than catching up across an update. ``text`` overrides the
    bundled notes (for testing); by default the bundled ``WHATS_NEW.md`` is read.
    ``installed_app`` overrides the install-kind check that gates the
    update-checks note (for testing); by default ``install_kind()`` answers it.
    """
    if text is None:
        text = _read_whats_new()
    if installed_app is None:
        installed_app = _is_installed_app()
    sections = parse_all_sections(text)

    cur_v = _safe_version(current)
    prev_v = _safe_version(last_seen)
    updating = (
        not on_demand
        and prev_v is not None and cur_v is not None and prev_v < cur_v
    )

    # The welcome framing is every showing that is neither a catch-up across an
    # update nor a Help-menu re-open: no stored last-seen version (the fresh
    # install), and the few strays that reach it the same way -- an unreadable
    # stored version, or a stored version not older than the running one.
    welcoming = not on_demand and not updating

    # The note is a welcome-framing thing *and* an installed-app thing: only
    # the installed app runs the startup check the note describes, so anywhere
    # else it would be telling the reader about something that never happens. The
    # framing on its own still decides which generic fallback body to use, which
    # is a question about who is reading rather than about what they installed.
    show_update_note = welcoming and installed_app

    if on_demand:
        orienter = "Recent releases"
    elif updating:
        orienter = f"What's new since {last_seen}"
    else:
        orienter = "Welcome to PyReconstruct"

    # Match the running version's own section by parsed VERSION, not raw string,
    # so a header spelled any PEP 440-equivalent way -- [1.20.4rc1] or
    # [1.20.4-rc.1] -- matches a 1.20.4rc1 runtime (mirrors whats_new_due).
    current_section = next(
        (s for s in sections
         if cur_v is not None and _safe_version(s["version"]) == cur_v),
        None,
    )
    friendly = (
        friendly_date(current_section["date"])
        if current_section and current_section["date"] else None
    )

    # No notes for the running version at all -> friendly generic body. An
    # indeterminate running version (an on-demand open where the version can't
    # be determined) instead falls through to the recent-history view below,
    # so the dialog still shows the notes it has.
    if current_section is None and not (cur_v is None and sections):
        body = GENERIC_WELCOME_NOTES if welcoming else GENERIC_NOTES
        return {"version": current, "date": friendly, "orienter": orienter,
                "body": _with_welcome_note(body) if show_update_note else body,
                "byline": MAINTAINER_BYLINE, "truncated": False}

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
        # Fresh install or on-demand re-open: the recent release history (the
        # current version plus the few before it), newest first and capped -- so
        # the reader sees what recent releases brought, not just the version
        # they happen to be running.
        shown = sorted(
            (s for s in sections
             if _safe_version(s["version"]) is not None
             and (cur_v is None or _safe_version(s["version"]) <= cur_v)),
            key=lambda s: _safe_version(s["version"]), reverse=True,
        )
        if len(shown) > cap:
            shown, truncated = shown[:cap], True

    body = _render_sections(shown, truncated)
    return {"version": current, "date": friendly, "orienter": orienter,
            "body": _with_welcome_note(body) if show_update_note else body,
            "byline": MAINTAINER_BYLINE, "truncated": truncated}

"""First-launch UX tests: silent username resolution and the What's-new gate.

All hermetic and headless -- the QSettings store and current-version lookup are
injected, so nothing touches the real user settings or pops a dialog.
"""
import pytest

from PyReconstruct.modules.gui.main import first_launch as F


# ---- fakes ------------------------------------------------------------------
class FakeSettings:
    """A QSettings-shaped dict so the gate/resolver can be tested without Qt I/O."""

    def __init__(self, data=None):
        self._d = dict(data or {})
        self.writes = []

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val
        self.writes.append((key, val))


class FakeSeries:
    user = None


# ---- username resolution ----------------------------------------------------
def test_resolve_username_uses_saved_name():
    s = FakeSeries()
    settings = FakeSettings({"username": "alice"})
    assert F.resolve_username(settings, s, default_factory=lambda: "oslogin") == "alice"
    assert s.user == "alice"
    assert settings.writes == []  # saved name reused, not rewritten


def test_resolve_username_falls_back_to_os_login_and_persists():
    s = FakeSeries()
    settings = FakeSettings()  # nothing saved
    assert F.resolve_username(settings, s, default_factory=lambda: "oslogin") == "oslogin"
    assert s.user == "oslogin"
    assert settings.writes == [("username", "oslogin")]


@pytest.mark.parametrize("saved", ["", "   ", None, 123, []])
def test_resolve_username_treats_empty_or_nonstring_as_unset(saved):
    settings = FakeSettings({"username": saved})
    assert F.resolve_username(settings, default_factory=lambda: "oslogin") == "oslogin"
    assert settings.writes == [("username", "oslogin")]


def test_resolve_username_default_of_last_resort():
    settings = FakeSettings()
    assert F.resolve_username(settings, default_factory=lambda: "") == "default"


# ---- what's-new version gate ------------------------------------------------
@pytest.mark.parametrize("stored,current,expected", [
    (None, "1.20.2", True),          # fresh install
    ("", "1.20.2", True),            # empty stored == fresh
    ("1.20.0", "1.20.2", True),      # after an update
    ("1.19.9", "1.20.0", True),
    ("1.20.2", "1.20.2", False),     # re-launch of a seen version
    ("1.21.0", "1.20.2", False),     # downgrade -> don't nag
    ("garbage", "1.20.2", True),     # corrupt stored -> show once, self-heals
    ("1.20.2", None, False),         # indeterminate current -> don't show
    (None, None, False),
    (None, "", False),
])
def test_whats_new_due(stored, current, expected):
    assert F.whats_new_due(stored, current) is expected


# ---- changelog parsing ------------------------------------------------------
SAMPLE = """# Changelog

## [Unreleased]

### Added
- Unreleased thing.

## [1.20.2] - 2026-07-01

### Fixed
- Silent username.
- What's new dialog.

## [1.20.0] - 2026-06-26

### Added
- Installers.
"""


def test_parse_changelog_section_finds_version():
    sec = F.parse_changelog_section(SAMPLE, "1.20.2")
    assert "Silent username." in sec
    assert "What's new dialog." in sec
    assert "Installers." not in sec      # stops at the next ## heading
    assert "Unreleased thing." not in sec


def test_parse_changelog_section_strips_v_prefix():
    assert F.parse_changelog_section(SAMPLE, "v1.20.2") == F.parse_changelog_section(SAMPLE, "1.20.2")


def test_parse_changelog_section_unreleased():
    assert "Unreleased thing." in F.parse_changelog_section(SAMPLE, "Unreleased")


def test_parse_changelog_section_missing_returns_none():
    assert F.parse_changelog_section(SAMPLE, "9.9.9") is None
    assert F.parse_changelog_section("", "1.20.2") is None
    assert F.parse_changelog_section(SAMPLE, "") is None


def test_parse_changelog_section_matches_beta_by_version():
    # setuptools-scm bakes a v1.21.0-beta-1 tag into the app as 1.21.0b1, so the
    # [1.21.0-beta-1] header must match a 1.21.0b1 runtime by PARSED version, not
    # raw string; the reverse spelling matches too.
    dashed = "## [1.21.0-beta-1] — 2026-07-07\n\n- Beta bullet.\n"
    assert "Beta bullet." in F.parse_changelog_section(dashed, "1.21.0b1")
    compact = "## [1.21.0b1] — 2026-07-07\n\n- Beta bullet.\n"
    assert "Beta bullet." in F.parse_changelog_section(compact, "1.21.0-beta-1")


# ---- friendly dates ---------------------------------------------------------
def test_friendly_date_formats_iso_without_leading_zero():
    assert F.friendly_date("2026-06-29") == "June 29, 2026"
    assert F.friendly_date("2026-01-05") == "January 5, 2026"


@pytest.mark.parametrize("bad", ["", None, "not-a-date", "2026/06/29", "June 2026", 20260629])
def test_friendly_date_returns_input_when_unparseable(bad):
    assert F.friendly_date(bad) == bad


# ---- multi-section parsing (versions + dates) -------------------------------
WN = """# What's New

intro paragraph, ignored.

## [1.20.3] — 2026-06-29

- Bullet three-A.
- Bullet three-B.

## [1.20.2] — 2026-06-20

- Bullet two.

## [1.20.1] — 2026-06-10

- Bullet one.
"""


def test_parse_all_sections_captures_version_date_and_body():
    secs = F.parse_all_sections(WN)
    assert [s["version"] for s in secs] == ["1.20.3", "1.20.2", "1.20.1"]
    assert secs[0]["date"] == "2026-06-29"
    assert "Bullet three-A." in secs[0]["body"]
    assert "intro paragraph" not in secs[0]["body"]   # pre-heading text is ignored


def test_parse_all_sections_empty_or_none():
    assert F.parse_all_sections("") == []
    assert F.parse_all_sections(None) == []


def test_parse_changelog_section_tolerates_em_dash_dated_heading():
    body = F.parse_changelog_section(WN, "1.20.2")
    assert "Bullet two." in body
    assert "Bullet three" not in body   # stops at the next heading


# ---- whats_new_content (header / orienter / section selection) --------------
def test_whats_new_fresh_install_shows_recent_history():
    c = F.whats_new_content("1.20.3", last_seen=None, text=WN)
    assert c["version"] == "1.20.3"
    assert c["date"] == "June 29, 2026"
    assert c["orienter"] == "Welcome to PyReconstruct"
    # a newcomer sees the recent releases (current + the ones before), newest first
    assert "### 1.20.3 — June 29, 2026" in c["body"]
    assert "### 1.20.2 — June 20, 2026" in c["body"]
    assert "### 1.20.1 — June 10, 2026" in c["body"]
    assert c["body"].index("1.20.3") < c["body"].index("1.20.2") < c["body"].index("1.20.1")
    assert c["truncated"] is False             # 3 sections, under the cap


def test_whats_new_skip_update_shows_missed_sections_newest_first():
    c = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    assert c["orienter"] == "What's new since 1.20.1"
    body = c["body"]
    assert "### 1.20.3 — June 29, 2026" in body
    assert "### 1.20.2 — June 20, 2026" in body
    assert "1.20.1" not in body                 # last_seen itself is excluded
    assert body.index("1.20.3") < body.index("1.20.2")   # newest first
    assert c["truncated"] is False


def test_whats_new_last_seen_immediate_previous_shows_current_only():
    c = F.whats_new_content("1.20.3", last_seen="1.20.2", text=WN)
    assert c["orienter"] == "What's new since 1.20.2"
    assert "### 1.20.3" in c["body"]
    assert "1.20.2" not in c["body"]            # only the one newer section
    assert c["truncated"] is False


def test_whats_new_caps_at_five_and_flags_truncation():
    versions = ["1.8.0", "1.7.0", "1.6.0", "1.5.0", "1.4.0", "1.3.0", "1.2.0"]
    text = "# What's New\n\n" + "\n".join(
        f"## [{v}] — 2026-06-15\n\n- Note for {v}.\n" for v in versions
    )
    c = F.whats_new_content("1.8.0", last_seen="1.1.0", text=text)
    assert c["truncated"] is True
    for v in versions[:5]:                      # newest five shown
        assert f"### {v}" in c["body"]
    for v in versions[5:]:                      # oldest two dropped
        assert f"### {v}" not in c["body"]
    assert "and earlier releases" in c["body"]


def test_whats_new_missing_current_section_falls_back_to_generic():
    c = F.whats_new_content("9.9.9", last_seen="1.20.1", text=WN)
    assert "Full release notes on GitHub" in c["body"]
    assert "Bullet" not in c["body"]            # never leaks other sections
    assert c["version"] == "9.9.9"
    assert c["truncated"] is False


def test_whats_new_matches_current_section_by_version_not_spelling():
    # The running version's own section is found by parsed VERSION, so a header
    # spelled any PEP 440-equivalent way matches. A dashed [1.20.4-rc.1] header
    # matches a compact 1.20.4rc1 runtime, and vice versa -- both render the RC
    # notes rather than falling back to the generic body.
    dashed = "# What's New\n\n## [1.20.4-rc.1] — 2026-07-03\n\n- RC bullet.\n"
    c = F.whats_new_content("1.20.4rc1", last_seen=None, text=dashed)
    assert "RC bullet." in c["body"]
    assert "Full release notes on GitHub" not in c["body"]   # matched, not generic

    compact = "# What's New\n\n## [1.20.4rc1] — 2026-07-03\n\n- RC bullet.\n"
    c2 = F.whats_new_content("1.20.4-rc.1", last_seen=None, text=compact)
    assert "RC bullet." in c2["body"]
    assert "Full release notes on GitHub" not in c2["body"]


def test_whats_new_downgrade_and_garbage_last_seen_are_treated_as_fresh():
    # downgrade: last_seen newer than current -> fresh; recent history up to current,
    # never anything newer than the running version
    c = F.whats_new_content("1.20.2", last_seen="1.99.0", text=WN)
    assert c["orienter"] == "Welcome to PyReconstruct"
    assert "### 1.20.2 — June 20, 2026" in c["body"]
    assert "### 1.20.1 — June 10, 2026" in c["body"]   # older releases shown too
    assert "1.20.3" not in c["body"]                   # never newer than current
    # unparseable last_seen -> fresh (recent history)
    c2 = F.whats_new_content("1.20.3", last_seen="garbage", text=WN)
    assert c2["orienter"] == "Welcome to PyReconstruct"
    assert "### 1.20.3" in c2["body"]
    assert "### 1.20.2" in c2["body"]


def test_whats_new_reads_bundled_file_and_is_offline_safe(monkeypatch, tmp_path):
    # the dialog body comes from WHATS_NEW.md (friendly), not the technical CHANGELOG
    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(WN, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    assert "Bullet three-A." in F.whats_new_content("1.20.3", last_seen=None)["body"]

    # nothing bundled -> friendly generic, never raises, never the network
    monkeypatch.setattr(F, "find_whats_new_path", lambda: None)
    assert "Full release notes on GitHub" in F.whats_new_content("1.20.3")["body"]


# ---- the maintainer byline (provenance line on every framing) ---------------
# The byline names who maintains this build, so a lab that installs it credits it
# correctly and reports its issues to the right person. It is a distinct field so
# the dialog can set it off from the notes as a quiet aside rather than mixing it
# into the release bullets, and it must be present on every framing.
BYLINE = "An independent build of PyReconstruct, maintained by Dusten Hubbard."


def test_maintainer_byline_constant_is_the_approved_text_verbatim():
    # Locked verbatim: it is maintainer-approved and checked to contain no fork
    # tells; a reword could reintroduce one.
    assert F.MAINTAINER_BYLINE == BYLINE


@pytest.mark.parametrize("kwargs", [
    {"last_seen": "1.20.1"},                 # an update
    {"last_seen": None},                     # a fresh install (welcome)
    {"on_demand": True},                     # the Help-menu re-open
    {"last_seen": None, "installed_app": True},   # welcome, installed app
])
def test_byline_is_present_on_every_framing_with_notes(kwargs):
    c = F.whats_new_content("1.20.3", text=WN, **kwargs)
    assert c["byline"] == BYLINE
    # it is a distinct field, never folded into the rendered notes body, so the
    # dialog renders it exactly once (below) and it can never double up
    assert BYLINE not in c["body"]


@pytest.mark.parametrize("kwargs", [
    {"last_seen": None},                     # welcome + generic fallback
    {"last_seen": "1.20.1"},                 # update + generic fallback
    {"on_demand": True},                     # on-demand + generic fallback
])
def test_byline_is_present_on_the_generic_fallback_body(kwargs):
    # a running version with no bundled section at all falls back to the generic
    # body; the byline rides along there too
    c = F.whats_new_content("9.9.9", text=WN, **kwargs)
    assert "Full release notes on GitHub" in c["body"]   # the generic body
    assert c["byline"] == BYLINE
    assert BYLINE not in c["body"]


def test_byline_is_present_when_nothing_is_bundled_at_all():
    c = F.whats_new_content("1.20.3", last_seen=None, text="")
    assert c["byline"] == BYLINE


# ---- github link ------------------------------------------------------------
def test_github_release_url_points_at_the_updater_repo():
    assert F.GITHUB_REPO in F.github_release_url()
    assert F.github_release_url("1.20.2").endswith("/releases/tag/v1.20.2")
    assert F.github_release_url("Unreleased").endswith("/releases")  # not a real tag
    assert F.github_release_url(None).endswith("/releases")


# ---- maybe_show_whats_new (gate + persistence, dialog stubbed) --------------
def _record_show():
    calls = []
    return calls, (lambda parent, version, last_seen=None: calls.append(version))


def test_maybe_show_fresh_install_shows_once_and_records():
    from PyReconstruct.modules.gui.dialog import whats_new as W
    calls, show = _record_show()
    settings = FakeSettings()
    assert W.maybe_show_whats_new(None, settings=settings, current="1.20.2", show=show) is True
    assert calls == ["1.20.2"]
    assert settings.value(F.WHATSNEW_KEY) == "1.20.2"
    # re-launch of the same version: no second show
    assert W.maybe_show_whats_new(None, settings=settings, current="1.20.2", show=show) is False
    assert calls == ["1.20.2"]


def test_maybe_show_after_update_shows_again():
    from PyReconstruct.modules.gui.dialog import whats_new as W
    calls, show = _record_show()
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.0"})
    assert W.maybe_show_whats_new(None, settings=settings, current="1.20.2", show=show) is True
    assert calls == ["1.20.2"]
    assert settings.value(F.WHATSNEW_KEY) == "1.20.2"


def test_maybe_show_skips_downgrade_and_unknown(monkeypatch):
    from PyReconstruct.modules.gui.dialog import whats_new as W
    calls, show = _record_show()
    down = FakeSettings({F.WHATSNEW_KEY: "1.21.0"})
    assert W.maybe_show_whats_new(None, settings=down, current="1.20.2", show=show) is False
    assert down.value(F.WHATSNEW_KEY) == "1.21.0"   # record left untouched
    # an indeterminate running version (current_version_str -> None): never show
    monkeypatch.setattr(W, "current_version_str", lambda: None)
    assert W.maybe_show_whats_new(None, settings=FakeSettings(), show=show) is False
    assert calls == []


def test_maybe_show_resolves_current_version_by_default(monkeypatch):
    """With no explicit current, it uses current_version_str() (the running build)."""
    from PyReconstruct.modules.gui.dialog import whats_new as W
    calls, show = _record_show()
    monkeypatch.setattr(W, "current_version_str", lambda: "2.0.0")
    assert W.maybe_show_whats_new(None, settings=FakeSettings(), show=show) is True
    assert calls == ["2.0.0"]


# ---- on-demand re-open (Help -> What's new) ----------------------------------
def test_whats_new_on_demand_shows_recent_history_not_welcome():
    """The Help-menu re-open: a returning user (no version change) gets the
    recent release history, framed as such -- never the fresh-install welcome."""
    c = F.whats_new_content("1.20.3", on_demand=True, text=WN)
    assert c["orienter"] == "Recent releases"
    assert "### 1.20.3 — June 29, 2026" in c["body"]
    assert "### 1.20.2 — June 20, 2026" in c["body"]
    assert "### 1.20.1 — June 10, 2026" in c["body"]
    assert c["body"].index("1.20.3") < c["body"].index("1.20.2")   # newest first


def test_whats_new_on_demand_ignores_last_seen():
    # even if a caller threads the stored last-seen through, on-demand means the
    # full recent history -- not the since-<last_seen> catch-up slice
    c = F.whats_new_content("1.20.3", last_seen="1.20.2", on_demand=True, text=WN)
    assert c["orienter"] == "Recent releases"
    assert "### 1.20.2" in c["body"]   # last_seen itself shown again
    assert "### 1.20.1" in c["body"]   # and everything before it


def test_show_whats_new_is_ungated_and_reopens_every_time(monkeypatch, tmp_path):
    """Unlike maybe_show_whats_new there is no once-per-version gate: every
    invocation shows, with the on-demand (recent-releases) content."""
    from PyReconstruct.modules.gui.dialog import whats_new as W
    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(WN, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    monkeypatch.setattr(W, "current_version_str", lambda: "1.20.3")

    shown = []
    show = lambda parent, version, last_seen=None, content=None: shown.append((version, content))
    W.show_whats_new(None, show=show)
    W.show_whats_new(None, show=show)          # no gate: shows again
    assert [v for v, _ in shown] == ["1.20.3", "1.20.3"]
    content = shown[0][1]
    assert content["orienter"] == "Recent releases"
    assert "### 1.20.3" in content["body"] and "### 1.20.2" in content["body"]


def test_help_menu_offers_whats_new_reopen():
    """The Help menu carries a 'What's new' action wired to the on-demand
    handler, alongside the existing update check."""
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.main.menubar import return_help_menu

    sentinel = lambda: None
    diag_sentinel = lambda: None
    stub = SimpleNamespace(
        copyCommit=lambda: None, checkForUpdates=lambda: None,
        showWhatsNew=sentinel, displayShortcuts=lambda: None,
        openWebsite=lambda *_: None, downloadExample=lambda: None,
        copyDiagnosticReport=diag_sentinel,
        viewLogFile=lambda: None, openLogFolder=lambda: None,
    )
    opts = return_help_menu(stub)["opts"]
    entries = [o for o in opts if isinstance(o, tuple)]
    whatsnew = [o for o in entries if o[0] == "whatsnew_act"]
    assert whatsnew == [("whatsnew_act", "What's new", "", sentinel)]

    # the copyable diagnostic report lives in the "Report issues" submenu
    issuemenu = [o for o in opts if isinstance(o, dict) and o["attr_name"] == "issuemenu"][0]
    copydiag = [o for o in issuemenu["opts"] if o[0] == "copydiag_act"]
    assert copydiag == [("copydiag_act", "Copy diagnostic report...", "", diag_sentinel)]


# ---- the welcome-only update-checks note ------------------------------------
# A newcomer has no way to discover that PyReconstruct checks for updates at
# all, or that the switches for it -- the check itself and the Beta channel --
# are in Series ▸ Options. The welcome showing is the one place that says so.
# The other two framings must stay clear of it: someone updating has just used
# the check, and someone reopening the notes from the Help menu went looking
# rather than needing to be oriented.
#
# These assert on distinctive fragments rather than the whole paragraph, so the
# copy can be reworded without failing a test for no reason -- but they do hold
# both facts the note exists to deliver: that the check can be turned off, and
# that a Beta channel exists.
def test_welcome_carries_the_update_checks_note():
    c = F.whats_new_content("1.20.3", last_seen=None, text=WN, installed_app=True)
    assert c["orienter"] == "Welcome to PyReconstruct"
    body = c["body"]
    assert "checks once a day" in body       # the app checks on its own
    assert "turn this off" in body           # and the check can be turned off
    assert "Beta channel" in body            # and there is a second channel
    assert "Series ▸ Options" in body        # where both of those live
    # an aside after the release history, set off by a rule -- not mistakable
    # for one more release bullet
    assert body.index("Bullet three-A.") < body.index("checks once a day")
    assert "\n---\n" in body


@pytest.mark.parametrize("last_seen", ["1.20.1", "1.20.2"])
def test_update_framing_never_carries_the_note(last_seen):
    """Someone updating already knows the check exists; they just used it.

    ``installed_app=True`` throughout, so it is the framing keeping the note
    out and not the install kind.
    """
    c = F.whats_new_content("1.20.3", last_seen=last_seen, text=WN, installed_app=True)
    assert c["orienter"] == f"What's new since {last_seen}"
    assert "checks once a day" not in c["body"]
    assert "Beta channel" not in c["body"]


@pytest.mark.parametrize("last_seen", [None, "1.20.2", "garbage"])
def test_on_demand_reopen_never_carries_the_note(last_seen):
    """The Help-menu re-open is a reader who went looking, not a newcomer.

    ``last_seen=None`` is the combination that would leak it: with nothing
    stored, the only thing separating this from a fresh install is the
    ``on_demand`` flag. ``installed_app=True`` throughout, so it is the framing
    keeping the note out and not the install kind.
    """
    c = F.whats_new_content("1.20.3", last_seen=last_seen, on_demand=True, text=WN,
                            installed_app=True)
    assert c["orienter"] == "Recent releases"
    assert "checks once a day" not in c["body"]
    assert "Beta channel" not in c["body"]


def test_welcome_note_survives_the_generic_fallback_body():
    """A build whose running version has no bundled section still orients.

    The body falls back to the friendly generic note there. A first-run reader
    on such a build is exactly the person who most needs telling, so the note
    rides along with the fallback rather than being lost with the sections.
    """
    c = F.whats_new_content("9.9.9", last_seen=None, text=WN, installed_app=True)
    assert c["orienter"] == "Welcome to PyReconstruct"
    assert "Full release notes on GitHub" in c["body"]   # the generic body
    assert "Bullet" not in c["body"]                     # still leaks no sections
    assert "checks once a day" in c["body"]
    assert "Series ▸ Options" in c["body"]

    # nothing bundled at all -- the generic body is the whole body
    c2 = F.whats_new_content("1.20.3", last_seen=None, text="", installed_app=True)
    assert "Full release notes on GitHub" in c2["body"]
    assert "Beta channel" in c2["body"]


@pytest.mark.parametrize("kwargs", [{"last_seen": "1.20.1"}, {"on_demand": True}])
def test_generic_fallback_carries_no_note_outside_the_welcome(kwargs):
    c = F.whats_new_content("9.9.9", text=WN, installed_app=True, **kwargs)
    assert "Full release notes on GitHub" in c["body"]   # the generic body
    assert "checks once a day" not in c["body"]


def test_welcome_note_reaches_the_stray_welcome_cases_too():
    """The welcome framing is not only the no-stored-version fresh install.

    ``whats_new_due`` also fires when the stored last-seen version cannot be
    parsed -- a corrupt record shows once and self-heals -- and that showing is
    framed as a welcome, so it carries the note. That is the right outcome: a
    reader whose record was lost is in a newcomer's position. A stored version
    not older than the running one welcomes for the same reason, though the
    startup gate declines to show it at all.
    """
    for last_seen in ("garbage", "1.99.0"):
        c = F.whats_new_content("1.20.2", last_seen=last_seen, text=WN, installed_app=True)
        assert c["orienter"] == "Welcome to PyReconstruct"
        assert "checks once a day" in c["body"]


# ---- the note is a claim about the installed app ----------------------------
# `MainWindow.checkForUpdatesStartup` returns early unless
# `install_kind() == "frozen"`, so anywhere else the note would be describing
# something that never happens. The gate compares against that one value rather
# than testing for "not source": `install_kind` answers "source" for a git
# checkout and a pip install alike today, and a kind added later should be
# excluded until someone decides otherwise, not included by default.
@pytest.mark.parametrize("kind,noted", [
    ("frozen", True),      # the installed app, the only one that checks
    ("source", False),     # git checkout and pip install alike
    ("flatpak", False),    # a kind nobody has added yet: excluded by default
    ("", False),
    (None, False),
])
def test_update_checks_note_is_limited_to_the_installed_app(monkeypatch, kind, noted):
    monkeypatch.setattr(F, "install_kind", lambda: kind)
    c = F.whats_new_content("1.20.3", last_seen=None, text=WN)
    assert c["orienter"] == "Welcome to PyReconstruct"   # welcomed either way
    assert "Bullet three-A." in c["body"]                # and shown the notes
    assert ("checks once a day" in c["body"]) is noted


def test_update_checks_note_is_silent_when_the_install_kind_cannot_be_read():
    """A broken detector must not cost the reader the release notes.

    The builder's contract is that it never raises; the note is the part that
    gets dropped, not the dialog.
    """
    def boom():
        raise RuntimeError("no install metadata")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(F, "install_kind", boom)
        c = F.whats_new_content("1.20.3", last_seen=None, text=WN)
    assert "Bullet three-A." in c["body"]
    assert "checks once a day" not in c["body"]


def test_installed_app_is_injectable_and_beats_the_detected_install_kind(monkeypatch):
    """The caller can answer the question, so a test need not patch the world."""
    monkeypatch.setattr(F, "install_kind", lambda: "source")
    noted = F.whats_new_content("1.20.3", last_seen=None, text=WN, installed_app=True)
    assert "checks once a day" in noted["body"]

    monkeypatch.setattr(F, "install_kind", lambda: "frozen")
    silent = F.whats_new_content("1.20.3", last_seen=None, text=WN, installed_app=False)
    assert "checks once a day" not in silent["body"]


# ---- the generic fallback greets a newcomer rather than thanking them --------
def test_generic_fallback_greets_under_the_welcome_framing():
    """Nobody updated on a first run, so do not thank the reader for updating.

    Turns on the framing the dialog already knows about. Independent of the
    install kind: a source build gets the right opener too, it just gets no
    update-checks note under it.
    """
    c = F.whats_new_content("9.9.9", last_seen=None, text=WN, installed_app=False)
    assert c["orienter"] == "Welcome to PyReconstruct"
    assert c["body"].startswith("Welcome to PyReconstruct.")
    assert "Thanks for updating" not in c["body"]
    assert "Full release notes on GitHub" in c["body"]   # still points at them
    assert "checks once a day" not in c["body"]          # source build: no note


@pytest.mark.parametrize("kwargs", [{"last_seen": "1.20.1"}, {"on_demand": True}])
def test_generic_fallback_keeps_the_updating_wording_everywhere_else(kwargs):
    """The wording that was already right stays exactly as it was."""
    c = F.whats_new_content("9.9.9", text=WN, installed_app=True, **kwargs)
    assert c["body"].startswith("Thanks for updating PyReconstruct.")
    assert "Welcome to PyReconstruct." not in c["body"]


# ---- startup-flow guard (first-run friction audit) --------------------------
def test_startup_username_resolver_has_no_path_to_a_prompt():
    """Guard the first-run flow against a reintroduced startup prompt.

    The startup audit confirmed the old "Enter your username" dialog was the
    only unprompted blocking modal on a fresh launch; every other startup modal
    is gated behind a user action. Lock that in for the username path: the
    silent resolver lives in a module that imports no Qt *widget*, so a
    focus-stealing prompt cannot creep back into startup username resolution.
    """
    import inspect
    src = inspect.getsource(F)
    for forbidden in ("QtWidgets", "QInputDialog", "QMessageBox", "QDialog", ".exec("):
        assert forbidden not in src, f"{forbidden} must not appear in the silent startup helper"


# ---- WhatsNewDialog widget (modeless + content wiring) ----------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def test_whats_new_dialog_is_modeless_and_renders_its_content(qapp):
    """Lock the hard spec guarantee: the dialog is MODELESS (never blocks
    startup), and the prominent header / body / link / button are wired up.

    A regression flipping setModal(False) -> True would reintroduce a
    startup-blocking modal -- the exact failure mode the first-launch audit
    guards against -- so assert it directly on the constructed widget.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    from PySide6.QtWidgets import QLabel, QPushButton

    content = {
        "version": "1.20.3", "date": "June 29, 2026",
        "orienter": "What's new since 1.20.1",
        "body": "### 1.20.3 — June 29, 2026\n\n- A shiny new thing.",
        "truncated": False,
    }
    dlg = WhatsNewDialog(None, "1.20.3", last_seen="1.20.1",
                         content=content, url="https://example.test/releases")
    try:
        assert dlg.isModal() is False                 # modeless: must not block startup
        assert "1.20.3" in dlg.windowTitle()
        labels = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
        assert "PyReconstruct 1.20.3" in labels       # prominent version header
        assert "Released June 29, 2026" in labels      # release date
        assert "What's new since 1.20.1" in labels     # orienter
        assert "Full release notes on GitHub" in labels
        assert "A shiny new thing." in dlg._notes.toPlainText()  # body rendered
        assert "Got it" in [b.text() for b in dlg.findChildren(QPushButton)]
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("kwargs,orienter", [
    ({"last_seen": "1.20.1"}, "What's new since 1.20.1"),   # an update
    ({"last_seen": None}, "Welcome to PyReconstruct"),      # a fresh install
    ({"on_demand": True}, "Recent releases"),              # the Help-menu re-open
    ({"last_seen": "1.20.1", "version": "9.9.9"}, None),   # the generic fallback
])
def test_dialog_renders_the_byline_once_below_the_notes(qapp, kwargs, orienter):
    """The real dialog puts the byline in its notes browser, exactly once, on
    every framing -- including the generic fallback (a running version with no
    bundled section). Asserted on the rendered QTextBrowser, not just the dict."""
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    version = kwargs.pop("version", "1.20.3")
    content = F.whats_new_content(version, text=WN, **kwargs)
    if orienter is not None:
        assert content["orienter"] == orienter
    dlg = WhatsNewDialog(None, version, content=content)
    try:
        rendered = dlg._notes.toPlainText()
        assert BYLINE in rendered                       # rendered, not just in the dict
        assert rendered.count(BYLINE) == 1              # exactly once, never twice
        # set off from the notes: it trails the body rather than leading it
        if content["body"]:
            first_body_line = content["body"].splitlines()[0].lstrip("#").strip()
            assert rendered.index(first_body_line) < rendered.index(BYLINE)
    finally:
        dlg.deleteLater()


def test_whats_new_on_demand_with_unknown_version_omits_it_and_still_opens(
        qapp, monkeypatch, tmp_path):
    """When the running version can't be determined, the on-demand dialog must
    never render "None" -- a version-free title, the orienter leading the
    dialog -- and it still opens showing the recent release notes."""
    from PyReconstruct.modules.gui.dialog import whats_new as W
    from PySide6.QtWidgets import QLabel

    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(WN, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    monkeypatch.setattr(W, "current_version_str", lambda: None)

    dlg = W.show_whats_new(None)
    try:
        assert dlg.isVisible()                        # still opens
        assert dlg.windowTitle() == "What's new in PyReconstruct"
        labels = [lab.text() for lab in dlg.findChildren(QLabel)]
        assert not any("None" in t for t in labels)   # no "PyReconstruct None"
        assert "Recent releases" in labels            # orienter as the header
        assert "Bullet three-A." in dlg._notes.toPlainText()  # recent notes shown
    finally:
        dlg.close()
        dlg.deleteLater()

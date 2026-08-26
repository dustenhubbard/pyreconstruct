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


def test_whats_new_caps_at_three_and_flags_truncation():
    versions = ["1.8.0", "1.7.0", "1.6.0", "1.5.0", "1.4.0", "1.3.0", "1.2.0"]
    text = "# What's New\n\n" + "\n".join(
        f"## [{v}] — 2026-06-15\n\n- Note for {v}.\n" for v in versions
    )
    c = F.whats_new_content("1.8.0", last_seen="1.1.0", text=text)
    assert c["truncated"] is True
    for v in versions[:3]:                      # newest three shown
        assert f"### {v}" in c["body"]
    for v in versions[3:]:                      # the rest dropped
        assert f"### {v}" not in c["body"]
    assert "and earlier releases" in c["body"]


def test_truncation_line_is_asterisk_emphasis_not_underscore():
    """Qt's markdown renderer (GitHub dialect) draws _underscore emphasis_ as
    UNDERLINE, so the pointer line rendered as one long dead-looking link
    until 2026-08-25. Asterisk emphasis renders as the intended italic."""
    text = "# What's New\n\n" + "\n".join(
        f"## [1.{n}.0] — 2026-06-15\n\n- Note.\n" for n in range(9, 1, -1)
    )
    c = F.whats_new_content("1.9.0", last_seen="1.0.0", text=text)
    assert c["truncated"] is True
    line = c["body"].splitlines()[-1]
    assert line.startswith("*") and line.endswith("*")
    assert "_" not in line


def test_whats_new_missing_current_section_falls_back_to_generic():
    c = F.whats_new_content("9.9.9", last_seen="1.20.1", text=WN)
    assert "All release notes on GitHub" in c["body"]
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
    assert "All release notes on GitHub" not in c["body"]   # matched, not generic

    compact = "# What's New\n\n## [1.20.4rc1] — 2026-07-03\n\n- RC bullet.\n"
    c2 = F.whats_new_content("1.20.4-rc.1", last_seen=None, text=compact)
    assert "RC bullet." in c2["body"]
    assert "All release notes on GitHub" not in c2["body"]


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
    assert "All release notes on GitHub" in F.whats_new_content("1.20.3")["body"]


# ---- the maintainer byline (provenance line on every framing) ---------------
# The byline names who maintains this build, so a lab that installs it credits it
# correctly and reports its issues to the right person. It is a distinct field so
# the dialog can set it off from the notes as a quiet aside rather than mixing it
# into the release bullets, and it must be present on every framing.
BYLINE = "An independent build of PyReconstruct, maintained by Dusten Hubbard."

# What the dialog's byline label actually shows: the same sentence broken into
# the approved mockup's two lines at the comma. The break is the dialog's
# display concern (an explicit <br/> in the markup); the constant above stays
# one string, which is what the GitHub release footer renders inline.
BYLINE_RENDERED = "An independent build of PyReconstruct,\nmaintained by Dusten Hubbard."


def test_maintainer_byline_constant_is_the_approved_text_verbatim():
    # Locked verbatim: it is maintainer-approved and checked to contain no fork
    # tells; a reword could reintroduce one.
    assert F.MAINTAINER_BYLINE == BYLINE
    # the two-line display form is the same words: only the break differs
    assert BYLINE_RENDERED.replace("\n", " ") == BYLINE


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
    assert "All release notes on GitHub" in c["body"]   # the generic body
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
    assert "### 1.20.3" in content["body"]


# ---- how much the Help-menu re-open pre-expands ------------------------------
#
# Updated deliberately: this path used to render the previous releases in full
# too, which on the shipped 1.21.0-beta-7 notes came to a 23,456-character
# scroll. The reader opened it for the version they are running, so that is what
# it opens on; the rest stays one click away rather than pre-expanded.

def _on_demand_body(monkeypatch, tmp_path, current="1.20.3"):
    """The content `show_whats_new` actually hands the dialog."""
    from PyReconstruct.modules.gui.dialog import whats_new as W
    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(WN, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    monkeypatch.setattr(W, "current_version_str", lambda: current)
    captured = []
    W.show_whats_new(
        None,
        show=lambda parent, version, last_seen=None, content=None: captured.append(content),
    )
    return captured[0]


def test_help_menu_reopen_shows_the_latest_three(monkeypatch, tmp_path):
    """The running version leads, with the two releases before it beneath:
    recent history, newest first (his ask, 2026-08-25)."""
    content = _on_demand_body(monkeypatch, tmp_path)
    assert content["body"].index("### 1.20.3") < content["body"].index("### 1.20.2")
    assert "Bullet three-A." in content["body"]        # its own notes, in full
    assert "### 1.20.2" in content["body"]
    assert "### 1.20.1" in content["body"]
    # exactly three sections in the fixture, so nothing was cut
    assert content["truncated"] is False


def test_help_menu_reopen_caps_at_three_and_stays_reachable(monkeypatch, tmp_path):
    """A fourth release drops off the reopen, and the truncation pointer is
    what keeps that honest."""
    from PyReconstruct.modules.gui.dialog import whats_new as W

    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(
        WN + "\n## [1.20.0] — 2026-06-01\n\n- Bullet zero.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    monkeypatch.setattr(W, "current_version_str", lambda: "1.20.3")
    captured = []
    W.show_whats_new(
        None,
        show=lambda parent, version, last_seen=None, content=None: captured.append(content),
    )
    content = captured[0]
    assert "### 1.20.1" in content["body"]
    assert "### 1.20.0" not in content["body"]
    assert content["truncated"] is True
    assert "and earlier releases" in content["body"]
    assert "full notes on GitHub" in content["body"]


def test_post_update_catch_up_still_renders_every_missed_release(monkeypatch, tmp_path):
    """Unchanged by the cap: someone updating across releases still gets them
    all. `ON_DEMAND_CAP` applies to the Help menu and nowhere else."""
    c = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    assert "### 1.20.3" in c["body"] and "### 1.20.2" in c["body"]
    assert c["truncated"] is False


def test_help_menu_offers_whats_new_reopen():
    """The Help menu carries a 'What's new' action wired to the on-demand
    handler, alongside the existing update check."""
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.main.menubar import return_help_menu

    sentinel = lambda: None
    diag_sentinel = lambda: None
    toggle_sentinel = lambda: None
    stub = SimpleNamespace(
        series=object(),
        copyCommit=lambda: None, checkForUpdates=lambda: None,
        showWhatsNew=sentinel, displayShortcuts=lambda: None,
        openWebsite=lambda *_: None, downloadExample=lambda: None,
        copyDiagnosticReport=diag_sentinel,
        viewLogFile=lambda: None, openLogFolder=lambda: None,
        toggleWhatsNewPopup=toggle_sentinel,
        toggleUpdateCheckOnStartup=toggle_sentinel,
        openMenuSearch=lambda: None,
        openOtherFlavorPage=lambda: None,
    )
    opts = return_help_menu(stub)["opts"]
    entries = [o for o in opts if isinstance(o, tuple)]
    whatsnew = [o for o in entries if o[0] == "whatsnew_act"]
    assert whatsnew == [("whatsnew_act", "What's new?", "", sentinel)]

    # ...and directly under it, the checkable popup on/off switch
    toggle = [o for o in entries if o[0] == "togglewhatsnew_act"]
    assert toggle == [("togglewhatsnew_act", "Turn off What's new pop-up",
                       "checkbox", toggle_sentinel)]
    assert entries.index(toggle[0]) == entries.index(whatsnew[0]) + 1

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
    assert "All release notes on GitHub" in c["body"]   # the generic body
    assert "Bullet" not in c["body"]                     # still leaks no sections
    assert "checks once a day" in c["body"]
    assert "Series ▸ Options" in c["body"]

    # nothing bundled at all -- the generic body is the whole body
    c2 = F.whats_new_content("1.20.3", last_seen=None, text="", installed_app=True)
    assert "All release notes on GitHub" in c2["body"]
    assert "Beta channel" in c2["body"]


@pytest.mark.parametrize("kwargs", [{"last_seen": "1.20.1"}, {"on_demand": True}])
def test_generic_fallback_carries_no_note_outside_the_welcome(kwargs):
    c = F.whats_new_content("9.9.9", text=WN, installed_app=True, **kwargs)
    assert "All release notes on GitHub" in c["body"]   # the generic body
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
    assert "All release notes on GitHub" in c["body"]   # still points at them
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


def rendered_text(label):
    """The text a QLabel actually shows, with any rich-text markup resolved."""
    from PySide6.QtGui import QTextDocumentFragment
    return QTextDocumentFragment.fromHtml(label.text()).toPlainText()


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
        assert "All release notes on GitHub" in labels
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
def test_dialog_renders_the_byline_once_as_its_own_widget(qapp, kwargs, orienter):
    """The real dialog renders the byline exactly once, on every framing --
    including the generic fallback (a running version with no bundled section)
    -- as its own label *outside* the notes browser.

    It used to be appended to the notes markdown, which put it inside the
    scrollable area: on a release with more than a screenful of notes a reader
    had to scroll to the bottom to see it. Asserted on the constructed widgets,
    not just the dict."""
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    from PySide6.QtWidgets import QLabel

    version = kwargs.pop("version", "1.20.3")
    content = F.whats_new_content(version, text=WN, **kwargs)
    if orienter is not None:
        assert content["orienter"] == orienter
    dlg = WhatsNewDialog(None, version, content=content)
    try:
        # not in the scroll any more: the browser carries the notes and nothing else
        assert BYLINE not in dlg._notes.toPlainText()
        # its own label, the approved words on the approved two lines, exactly
        # once across the whole dialog. The label carries link markup now, so
        # compare what it *renders*.
        assert dlg._byline is not None
        assert rendered_text(dlg._byline) == BYLINE_RENDERED
        labels = [lab for lab in dlg.findChildren(QLabel)
                  if BYLINE_RENDERED in rendered_text(lab)]
        assert labels == [dlg._byline]
    finally:
        dlg.deleteLater()


def test_dialog_byline_breaks_into_two_lines_at_the_comma(qapp):
    """The byline renders as the mockup's two lines, broken at the comma.

    Line one "An independent build of PyReconstruct," and line two
    "maintained by Dusten Hubbard.", at every window width: the break is an
    explicit ``<br/>`` in the markup rather than word-wrap luck, so widening
    the dialog cannot flatten it back to one line and narrowing it cannot
    move the break somewhere else. The break is a display concern of this
    dialog alone; ``MAINTAINER_BYLINE`` stays one string (pinned verbatim
    above), which is what the GitHub release footer renders inline.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        # the break, exactly where the mockup puts it
        assert ",<br/>" in dlg._byline.text()
        first, second = rendered_text(dlg._byline).split("\n")
        assert first == "An independent build of PyReconstruct,"
        assert second == "maintained by Dusten Hubbard."

        # rendered as exactly two lines at the default width and much wider
        dlg.show()
        line = dlg._byline.fontMetrics().height()
        for width in (700, 1100):
            dlg.resize(width, 620)
            assert 2 * line <= dlg._byline.height() < 3 * line, (
                f"byline is not two lines tall at width {width}"
            )
    finally:
        dlg.deleteLater()


def test_dialog_byline_and_link_share_a_footer_row_below_the_notes(qapp):
    """The byline is a footer under the notes, sharing one row with the link.

    The approved placement: byline bottom-left and the "Full release notes on
    GitHub" link bottom-right of the same row, below the scrollable notes
    browser and above the action buttons. The byline stays outside the scroll,
    so it is on screen from the moment the dialog opens; sharing the row keeps
    the two small-text footer items from stacking into what reads as a single
    block. Asserted as rendered geometry rather than layout indexes, so any
    layout that produces the row counts and none that merely declares it does.

    This is also the regression probe for keeping the byline out of the notes.
    Reverting that fix, by appending ``_{byline}_`` back onto
    ``content["body"]`` before building the browser, leaves ``dlg._byline``
    unbuilt and the byline back inside ``dlg._notes.toPlainText()``.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    from PySide6.QtWidgets import QLabel, QPushButton

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        dlg.resize(760, 620)
        dlg.layout().activate()
        link = next(lab for lab in dlg.findChildren(QLabel)
                    if "All release notes on GitHub" in lab.text())
        byline, notes = dlg._byline, dlg._notes
        # outside the scrollable area: the browser carries the notes and
        # nothing else, and the byline widget does not hang off the browser
        assert BYLINE not in notes.toPlainText()
        assert not notes.isAncestorOf(byline)
        # below the notes...
        assert byline.geometry().top() >= notes.geometry().bottom()
        # ...on the same row as the link: their vertical extents overlap...
        assert byline.geometry().top() < link.geometry().bottom()
        assert link.geometry().top() < byline.geometry().bottom()
        # ...with the byline on the left and the link on the right
        assert byline.geometry().right() < link.geometry().left()
        # the action buttons are the row below the footer
        got_it = next(b for b in dlg.findChildren(QPushButton)
                      if b.text() == "Got it")
        assert got_it.geometry().top() >= byline.geometry().bottom()
        assert got_it.geometry().top() >= link.geometry().bottom()
        # and the footer keeps the byline's register: italic, name linked
        assert byline.font().italic() is True
        assert f'<a href="{F.HOMEPAGE_URL}">{F.LINKED_NAME}</a>' in byline.text()
    finally:
        dlg.deleteLater()


def test_dialog_minimum_size_and_where_extra_space_goes(qapp):
    """Minimum width 700, notes browser at least 320 tall, growth goes to notes.

    The numbers are the review record for the 2026-08-12 size bump, chosen
    rather than inherited, and click-tested and approved by Dusten at these
    values:

    * Width 540 -> 700. The byline's two-line shape is an explicit break (see
      ``test_dialog_byline_breaks_into_two_lines_at_the_comma``), the same at
      every width, so the width is not what shapes the footer; the extra room
      is about how much of a release note line fits unwrapped.
    * The notes browser's minimum height 260 -> 320, which is the entirety of
      the height increase (about 13% on the whole dialog at the default
      size): the notes are the one part of the dialog worth more room, and
      the taller default still fits a 13 inch laptop screen with room to
      spare.

    The growth half pins WHERE size goes rather than a pixel sum: stretching
    the dialog must stretch the scrollable notes and leave the byline and the
    button row their own heights, or a taller dialog would just spread its
    footer chrome apart.
    """
    from PySide6.QtWidgets import QPushButton
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        assert dlg.minimumWidth() == 700
        assert dlg._notes.minimumHeight() == 320

        # shown (offscreen), so resizes relayout immediately: on a hidden
        # widget the LayoutRequest a resize posts is deferred until show, and
        # the child geometry below would still be the pre-resize one
        dlg.show()
        assert dlg.width() == 700

        # stretching the dialog stretches the notes, not the footer rows
        got_it = next(b for b in dlg.findChildren(QPushButton)
                      if b.text() == "Got it")
        notes_h = dlg._notes.height()
        byline_h, button_h = dlg._byline.height(), got_it.height()
        dlg.resize(dlg.width(), dlg.height() + 200)
        assert dlg._notes.height() >= notes_h + 180   # the browser absorbed it
        assert dlg._byline.height() == byline_h
        assert got_it.height() == button_h
    finally:
        dlg.deleteLater()


def test_dialog_omits_the_byline_widget_when_the_content_has_none(qapp):
    """No byline field -> no label at all, rather than an empty muted line."""
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    from PySide6.QtWidgets import QLabel

    content = {"version": "1.20.3", "date": None, "orienter": "Recent releases",
               "body": "- A thing.", "truncated": False}
    dlg = WhatsNewDialog(None, "1.20.3", content=content, url="https://example.test")
    try:
        assert dlg._byline is None
        assert not any("An independent build" in rendered_text(lab)
                       for lab in dlg.findChildren(QLabel))
    finally:
        dlg.deleteLater()


def test_dialog_byline_is_italic_and_not_muted(qapp):
    """The byline is italic, unbolded, enabled, and never disabled-role dim.

    The italic carries the aside register the markdown ``_..._`` gave it. The
    color is the shared secondary style the release date uses (pinned in
    ``test_dialog_date_and_byline_share_the_secondary_style``); what this test
    guards against is the failure mode below that style: an earlier revision
    dimmed the line via ``setEnabled(False)``, which borrowed the disabled
    palette role and rendered it at roughly 1.6:1 against the dialog
    background, switched-off rather than secondary. Who maintains this build
    is what a lab needs in order to report an issue to the right person, so
    the pixel tests below still hold the rendered contrast above that broken
    1.6:1 (the floor is 2.0:1; the maintainer chose the light 0.34 blend, at
    about 2.3:1, off a measured ladder, see SECONDARY_TEXT_BLEND). Asserted
    on the constructed widget: a regression restoring the disabled state, or
    setting the weight instead of the slant, fails here.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        font = dlg._byline.font()
        assert font.italic() is True
        assert font.bold() is False
        assert font.underline() is False       # no underline decoration, ever
        assert font.strikeOut() is False
        # not the disabled color role: enabled in its own right and with an
        # enabled ancestry, so the label paints from the Active group.
        assert dlg._byline.isEnabled() is True
        assert dlg._byline.isEnabledTo(dlg) is True
    finally:
        dlg.deleteLater()


def test_dialog_date_and_byline_share_the_secondary_style(qapp):
    """The release date and the byline are the dialog's two secondary lines.

    Both are italic and both paint in the same palette-derived secondary
    color, so they read as one register: quieter than the body text, darker
    than the near-invisible disabled gray the date line used to borrow
    through ``setEnabled(False)``. Pinned as the relationship rather than as
    pixel values: the shared color must sit strictly between the dialog
    background and the full text lightness (the blend's own endpoints), and
    both labels must spell exactly that color into their markup, so the
    assertions hold under any theme without naming one.
    """
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QLabel
    from PyReconstruct.modules.gui.dialog.whats_new import (
        WhatsNewDialog, secondary_text_color,
    )

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    assert content["date"], "fixture notes must carry a release date"
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        date_lab = next(lab for lab in dlg.findChildren(QLabel)
                        if "Released" in lab.text())
        # both italic: the shared aside register
        assert date_lab.font().italic() is True
        assert dlg._byline.font().italic() is True
        # the date is a real enabled label now, not the disabled-role dimming
        assert date_lab.isEnabled() is True
        # one shared color, spelled identically into both labels' markup
        color = secondary_text_color(dlg.palette())
        assert f"color:{color.name()}" in date_lab.text()
        assert f"color:{color.name()}" in dlg._byline.text()
        # ...and that color sits strictly between the dialog background and
        # the full text lightness -- visible, and quieter than the body --
        # whichever way the active theme points
        text = dlg.palette().color(QPalette.Active, QPalette.WindowText)
        bg = dlg.palette().color(QPalette.Active, QPalette.Window)
        lo, hi = sorted((text.lightness(), bg.lightness()))
        assert lo < color.lightness() < hi
    finally:
        dlg.deleteLater()


def test_secondary_color_survives_the_cocoa_degenerate_palette(qapp):
    """A palette whose Disabled and Active text are both black still yields gray.

    The regression this pins was invisible to every headless run: on macOS
    (cocoa) the palette carries ``Disabled WindowText == Active WindowText ==
    #000000``, because the macOS style dims disabled text at paint time rather
    than in the palette. The first secondary blend interpolated disabled
    toward active, which on that palette returns pure black at every
    fraction, so Dusten saw solid dark text while offscreen/Fusion (#bebebe
    disabled) rendered the intended gray on every CI and local test run. The
    blend now runs background-to-text, endpoints no readable theme can leave
    equal; this feeds it the exact cocoa shape and requires a real
    intermediate gray.
    """
    from PySide6.QtGui import QColor, QPalette
    from PyReconstruct.modules.gui.dialog.whats_new import secondary_text_color

    cocoa = QPalette()
    cocoa.setColor(QPalette.Active, QPalette.WindowText, QColor("#000000"))
    cocoa.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#000000"))
    cocoa.setColor(QPalette.Active, QPalette.Window, QColor("#ececec"))

    color = secondary_text_color(cocoa)
    assert color != QColor("#000000"), "degenerated to the text color"
    assert color != QColor("#ececec"), "degenerated to the background"
    # strictly between the endpoints: a gray, not either extreme
    assert 0 < color.lightness() < QColor("#ececec").lightness()


def measure_byline_pixels(dlg):
    """Read the byline's actual rendered pixels out of the dialog.

    The line is deliberately two-toned: the project name is an ordinary link
    (blue, underlined) and everything around it is plain italic text. So the ink
    is split by color -- a pixel counts as link ink when its blue channel leads
    its red one by a clear margin, which holds in both themes (link #4747fa vs
    text #000000 in the default one, #1a5a90 vs #dfe1e2 under qdark) -- and each
    part is measured on its own.

    Underlines are found by the longest *unbroken* horizontal run of ink. An
    underline is one continuous rule about as wide as the text it sits under;
    the glyph rows of a sentence are always broken into many short runs by the
    spaces between words. Counting ink per row cannot tell those apart, since
    the x-height rows of ordinary text fill most of a line too.

    All x values in the result are relative to the label's own left edge.

    The label is rendered with *grayscale* antialiasing for the measurement, and
    that line is load-bearing rather than tidying. Qt's FreeType backend
    antialiases text with RGB **subpixel** rendering on Linux, which fringes the
    edge of every glyph with color: the plain black sentence comes back carrying
    pixels like (18, 68, 146) and (148, 220, 238), whose blue channel leads their
    red by far more than the margin above uses to recognise link ink. Split by
    color, most of the line then reads as link -- ``link_span`` (1, 432) rather
    than the project name's (147, 234) -- and the underline check compares the
    name's real 86px rule against a 432px span that is mostly plain text. That is
    exactly how this failed on CI while passing every macOS run, at 87px of
    433px: CoreText hands back grayscale coverage, so there are no fringes to
    misread and the bug cannot appear there. Reproduced in an ubuntu:24.04
    container with the workflow's own apt line, at 86px of 432px.

    The rendering itself is correct on Linux -- grabbed and inspected, the name
    and only the name is blue and underlined -- so this is a measurement that
    does not survive the platform, not a link that does not draw.
    ``NoSubpixelAntialias`` changes only how glyph edges are filtered: metrics,
    layout, the palette roles the two halves of the line paint from, and the
    underline (a filled rectangle, never a glyph) are identical either way, and
    the macOS figures are unchanged to the pixel by setting it. It is set
    unconditionally rather than under a platform check, so both platforms measure
    the same rendering and macOS cannot quietly stop covering the Linux path.
    """
    from PySide6.QtGui import QColor, QFont, QImage

    font = dlg._byline.font()
    font.setStyleStrategy(
        QFont.StyleStrategy(font.styleStrategy().value
                            | QFont.StyleStrategy.NoSubpixelAntialias.value)
    )
    dlg._byline.setFont(font)

    # The x-coordinate mapping below reads the byline's FIRST line, which the
    # explicit two-line break guarantees is "An independent build of
    # <PyReconstruct>," at every width; the second line contributes only plain
    # ink, which the measurements below already tolerate on either side of the
    # anchor. 760 just gives the grab a stable, roomy canvas past the 700
    # minimum.
    dlg.resize(760, 620)
    dlg.layout().activate()
    pixmap = dlg.grab()
    ratio = pixmap.devicePixelRatio()
    image = pixmap.toImage().convertToFormat(QImage.Format_RGB32)

    rect = dlg._byline.geometry()
    x0, y0 = int(rect.left() * ratio), int(rect.top() * ratio)
    x1 = min(int(rect.right() * ratio), image.width() - 1)
    y1 = min(int(rect.bottom() * ratio), image.height() - 1)
    assert x1 > x0 and y1 > y0, "byline has no rendered rect to sample"

    def rgb(x, y):
        return QColor(image.pixel(x, y)).getRgb()[:3]

    def luminance(color):
        def channel(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (channel(c) for c in color)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    background = rgb(x1 - 1, y0)          # sampled past the end of the text

    def is_ink(color):
        return sum(abs(a - b) for a, b in zip(color, background)) > 30

    def is_link_colored(color):
        return color[2] - color[0] > 40

    link_xs, plain_xs, plain_ink, link_ink = [], [], [], []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            color = rgb(x, y)
            if not is_ink(color):
                continue
            if is_link_colored(color):
                link_xs.append(x)
                link_ink.append(color)
            else:
                plain_xs.append(x)
                plain_ink.append(color)

    assert plain_xs, "the byline drew no plain text at all"

    def longest_run(lo, hi):
        """Longest unbroken run of ink in the column band [lo, hi]."""
        best = 0
        for y in range(y0, y1 + 1):
            current = 0
            for x in range(lo, hi + 1):
                if is_ink(rgb(x, y)):
                    current += 1
                else:
                    best = max(best, current)
                    current = 0
            best = max(best, current)
        return best

    def separation(color):
        a, b = luminance(color), luminance(background)
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)

    from collections import Counter

    boldest = max(plain_ink, key=separation)
    result = dict(background=background, plain_ink=boldest,
                  plain_contrast=separation(boldest), link_span=None,
                  link_width=0, link_longest_run=0,
                  link_ink=Counter(link_ink).most_common(1)[0][0] if link_ink
                  else None)

    # the plain text runs either side of the link; measure the longer side
    if link_xs:
        lo, hi = min(link_xs), max(link_xs)
        result["link_span"] = (lo - x0, hi - x0)
        result["link_width"] = hi - lo + 1
        result["link_longest_run"] = longest_run(lo, hi)
        before = longest_run(x0, lo - 1) if lo - 1 > x0 else 0
        after = longest_run(hi + 1, x1) if x1 > hi + 1 else 0
        result["plain_longest_run"] = max(before, after)
        result["plain_width"] = max(lo - 1 - x0, x1 - hi - 1)
    else:
        result["plain_longest_run"] = longest_run(x0, x1)
        result["plain_width"] = max(plain_xs) - min(plain_xs) + 1
    return result


def test_dialog_byline_renders_dark_and_unbroken(qapp):
    """Pixel-level: the plain part of the byline is high-contrast, un-underlined.

    The property assertions above can all hold while the widget still paints
    wrong -- ``setEnabled(False)`` on an ancestor, a palette override, an
    unhonoured CSS rule -- so this reads the actual rendered pixels. The
    contrast must clear 2.0:1: the disabled rendering this replaced measured
    ~1.6:1 and was reported unreadable, while the maintainer's chosen 0.34
    blend (see SECONDARY_TEXT_BLEND) renders about 2.3:1, so the threshold
    sits between the broken look and the chosen one. The window is narrow by
    his choice of a light gray; the exact-color pin in the shared-style test
    is what guards the other direction, a repaint back toward black. And the
    plain text must carry no underline; the linked project name is allowed
    one and is checked separately below.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        m = measure_byline_pixels(dlg)
        assert m["plain_contrast"] >= 2.0, (
            f"byline ink {m['plain_ink']} on {m['background']} is only "
            f"{m['plain_contrast']:.2f}:1 -- that is the switched-off disabled "
            "look, not the chosen secondary gray"
        )
        assert m["plain_longest_run"] < 0.85 * m["plain_width"], (
            f"an unbroken {m['plain_longest_run']}px run across "
            f"{m['plain_width']}px of plain text: the sentence is underlined"
        )
    finally:
        dlg.deleteLater()


def test_dialog_byline_links_only_the_project_name(qapp):
    """Only the words "PyReconstruct" are a link; the sentence around it is not.

    Asserted on the pixels, because this is the whole design of the line: one
    ordinary blue underlined link inside plain italic text. The link ink is
    found by color and must be underlined across its own width, while the text
    either side of it must not be. The rendered span is also checked against
    where the font metrics say the word falls, so a markup change that linked
    the wrong run of characters -- or the whole sentence -- fails here.
    """
    from PySide6.QtGui import QFontMetrics
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        m = measure_byline_pixels(dlg)
        assert m["link_span"] is not None, "nothing in the byline is link-colored"

        # the link is underlined: one unbroken rule the width of the word
        assert m["link_longest_run"] >= 0.85 * m["link_width"], (
            f"the linked name shows no underline (longest run "
            f"{m['link_longest_run']}px of {m['link_width']}px)"
        )
        # ...and the plain text around it is not
        assert m["plain_longest_run"] < 0.85 * m["plain_width"]

        # the link covers the project name and nothing else
        metrics = QFontMetrics(dlg._byline.font())
        lead = metrics.horizontalAdvance(BYLINE[:BYLINE.index(F.LINKED_NAME)])
        word = metrics.horizontalAdvance(F.LINKED_NAME)
        start, end = m["link_span"]
        assert abs(start - lead) <= 4, (
            f"link ink starts at x={start}, the name starts at x={lead}"
        )
        assert abs(end - (lead + word)) <= 4, (
            f"link ink ends at x={end}, the name ends at x={lead + word}"
        )
    finally:
        dlg.deleteLater()


def test_dialog_byline_stays_legible_under_the_dark_theme(qapp):
    """The byline must stay readable under the theme Help > Theme installs.

    The plain text and the link both take their color from the palette -- the
    sentence from the ordinary text role, the anchor from QPalette::Link -- so
    both follow the theme without this code naming a color. An earlier revision
    sampled a color into the markup instead and rendered the line
    black-on-charcoal at 1.32:1 under qdark, so the dark theme is asserted
    directly rather than assumed to follow from the light one.
    """
    from PySide6.QtWidgets import QApplication
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    import qdarkstyle

    app = QApplication.instance()
    previous = app.styleSheet()
    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = None
    try:
        app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6())
        dlg = WhatsNewDialog(None, "1.20.3", content=content,
                             url="https://example.test/releases")
        m = measure_byline_pixels(dlg)
        # same 2.0:1 floor as the light-theme pixel test, for the same reason
        # (see SECONDARY_TEXT_BLEND: the maintainer chose a light secondary
        # gray at about 2.3:1, and the floor separates it from the broken
        # disabled look rather than enforcing 4.5:1)
        assert m["plain_contrast"] >= 2.0, (
            f"under the dark theme the byline renders {m['plain_ink']} on "
            f"{m['background']} -- {m['plain_contrast']:.2f}:1"
        )
        assert m["plain_longest_run"] < 0.85 * m["plain_width"], (
            "the sentence is underlined under qdark"
        )
        assert m["link_span"] is not None, (
            "the linked name is not link-colored under qdark"
        )
    finally:
        if dlg is not None:
            dlg.deleteLater()
        app.setStyleSheet(previous)   # never leak the theme into other tests


def test_dialog_byline_link_color_follows_a_live_theme_switch(qapp):
    """Switching theme with the dialog open must recolor the link, not strand it.

    QLabel resolves ``QPalette::Link`` into its ``QTextDocument`` when the text
    is set, so an anchor keeps the color of whatever theme was active at
    construction while the plain text around it follows the palette. Left alone,
    switching to the dark theme with this dialog open renders the linked name in
    the light theme's blue at 1.85:1 against the dark background.

    The reference is a dialog *built fresh* under the target theme rather than a
    fixed number: that is the color the switched dialog is supposed to end up
    with, and comparing against it cannot drift if qdarkstyle changes its link
    color. Both directions are exercised, because the app's theme switch takes
    two different code paths -- the dark branch only sets a stylesheet, the
    light branch also sets a palette.
    """
    from PySide6.QtWidgets import QApplication
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog
    import qdarkstyle

    app = QApplication.instance()
    previous = app.styleSheet()
    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)

    def build():
        return WhatsNewDialog(None, "1.20.3", content=content,
                              url="https://example.test/releases")

    def go_dark():
        app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6())

    def go_light():
        app.setStyleSheet("")
        app.setPalette(app.style().standardPalette())

    switched = fresh_dark = fresh_light = None
    try:
        go_light()
        switched = build()
        light_ink = measure_byline_pixels(switched)["link_ink"]

        # ...now switch underneath it
        go_dark()
        after_dark = measure_byline_pixels(switched)
        fresh_dark = build()
        assert after_dark["link_ink"] == measure_byline_pixels(fresh_dark)["link_ink"], (
            f"after switching to the dark theme the open dialog's link is "
            f"{after_dark['link_ink']}, but a dialog built fresh under it "
            "renders a different color -- the anchor color is stale"
        )
        assert after_dark["link_ink"] != light_ink

        # ...and back, which is the branch that also sets a palette
        go_light()
        after_light = measure_byline_pixels(switched)
        fresh_light = build()
        assert after_light["link_ink"] == measure_byline_pixels(fresh_light)["link_ink"]
        assert after_light["link_ink"] == light_ink
    finally:
        for dlg in (switched, fresh_dark, fresh_light):
            if dlg is not None:
                dlg.deleteLater()
        app.setStyleSheet(previous)
        app.setPalette(app.style().standardPalette())


def test_dialog_byline_is_a_link_to_the_home_page(qapp):
    """The project name in the byline jumps to the home page.

    A real ``<a href>`` with ``setOpenExternalLinks(True)``, so Qt follows it
    and the dialog wires up no handler of its own. The escaping runs before the
    anchor is spliced in, and the visible text is unchanged by the markup.
    """
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        markup = dlg._byline.text()
        assert F.HOMEPAGE_URL == "https://pyreconstruct.org"
        assert f'<a href="{F.HOMEPAGE_URL}">{F.LINKED_NAME}</a>' in markup
        # exactly one anchor, wrapping exactly the name
        assert markup.count("<a ") == 1
        assert dlg._byline.openExternalLinks() is True
        # the sentence still reads as itself once the markup is resolved,
        # on the two approved lines
        assert rendered_text(dlg._byline) == BYLINE_RENDERED
        # the name occurs once in the byline, so the first-occurrence split is
        # unambiguous; if it ever occurred zero times there would be no anchor
        assert BYLINE.count(F.LINKED_NAME) == 1
    finally:
        dlg.deleteLater()


def test_dialog_byline_click_activates_only_on_the_project_name(qapp):
    """Clicking the name follows the link; clicking the rest of the line does not.

    Driven through real mouse clicks on the widget rather than by emitting the
    signal, so this measures Qt's own hit-testing of the anchor. ``linkActivated``
    is only observable with ``openExternalLinks`` off -- with it on, Qt consumes
    the click and opens the URL instead -- so it is switched off for the test,
    which also keeps any browser from being launched.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtTest import QTest
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = F.whats_new_content("1.20.3", last_seen="1.20.1", text=WN)
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        # 760 for the same reason measure_byline_pixels resizes to 760: a
        # stable, roomy canvas past the 700 minimum. The click coordinates
        # below address the byline's FIRST line, which the explicit two-line
        # break guarantees is "An independent build of <PyReconstruct>," at
        # every width.
        dlg.resize(760, 620)
        dlg.show()
        label = dlg._byline
        label.setOpenExternalLinks(False)     # so the signal is observable
        fired = []
        label.linkActivated.connect(fired.append)

        metrics = QFontMetrics(label.font())
        lead = metrics.horizontalAdvance(BYLINE[:BYLINE.index(F.LINKED_NAME)])
        word = metrics.horizontalAdvance(F.LINKED_NAME)
        line = metrics.height()
        middle = line // 2                    # vertical center of line one

        def click(x, y=middle):
            fired.clear()
            QTest.mouseClick(label, Qt.LeftButton, Qt.NoModifier,
                             QPoint(x, y))
            return list(fired)

        # inside the word, at both ends and the middle
        for x in (lead + 2, lead + word // 2, lead + word - 2):
            assert click(x) == [F.HOMEPAGE_URL], f"no activation at x={x}"
        # outside it, including immediately either side
        for x in (8, lead - 8, lead + word + 8, lead + word + 140):
            assert click(x) == [], f"the line activated at x={x}, off the name"
        # and the second line is not the anchor, even directly below the name
        assert click(lead + word // 2, y=middle + line) == [], (
            "the anchor leaked onto the byline's second line"
        )
    finally:
        dlg.deleteLater()


def test_dialog_link_stays_right_when_the_content_has_no_byline(qapp):
    """No byline still leaves the GitHub link on the right edge of its row.

    The byline is what pushes the link rightward in the footer, and some
    framings carry no byline at all. Without something taking its place the
    link would slide to the left edge on exactly those framings, so the footer
    keeps a stretch where the byline would be and the link stays put whether
    the provenance line is there or not.
    """
    from PySide6.QtWidgets import QLabel
    from PyReconstruct.modules.gui.dialog.whats_new import WhatsNewDialog

    content = {"version": "1.20.3", "date": None, "orienter": "Recent releases",
               "body": "- A thing.", "truncated": False}
    dlg = WhatsNewDialog(None, "1.20.3", content=content,
                         url="https://example.test/releases")
    try:
        dlg.resize(760, 620)
        dlg.layout().activate()
        assert dlg._byline is None
        link = next(lab for lab in dlg.findChildren(QLabel)
                    if "All release notes on GitHub" in lab.text())
        # right-aligned: the link's whole width sits in the right half
        assert link.geometry().left() > dlg.width() // 2
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

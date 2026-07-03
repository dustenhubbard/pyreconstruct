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

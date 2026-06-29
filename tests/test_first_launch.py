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


def test_release_notes_shows_friendly_highlights_then_generic(monkeypatch, tmp_path):
    # the dialog body comes from WHATS_NEW.md (friendly), not the technical CHANGELOG
    wn = tmp_path / "WHATS_NEW.md"
    wn.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: wn)
    assert "Silent username." in F.release_notes_markdown("1.20.2")          # exact version

    # no highlights section for this version -> friendly generic, never raw changelog
    generic = F.release_notes_markdown("9.9.9")
    assert "release notes on GitHub" in generic.lower() or "Full release notes" in generic
    assert "Unreleased thing." not in generic

    monkeypatch.setattr(F, "find_whats_new_path", lambda: None)              # nothing bundled
    generic2 = F.release_notes_markdown("1.20.2")
    assert "Full release notes on GitHub" in generic2


# ---- github link ------------------------------------------------------------
def test_github_release_url_points_at_the_updater_repo():
    assert F.GITHUB_REPO in F.github_release_url()
    assert F.github_release_url("1.20.2").endswith("/releases/tag/v1.20.2")
    assert F.github_release_url("Unreleased").endswith("/releases")  # not a real tag
    assert F.github_release_url(None).endswith("/releases")


# ---- maybe_show_whats_new (gate + persistence, dialog stubbed) --------------
def _record_show():
    calls = []
    return calls, (lambda parent, version: calls.append(version))


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

"""The What's-new dialog on a dev build shows the latest stable's notes.

A nightly (``1.24.0.dev20261007``) or a source checkout of main
(``1.24.0.dev5+g0123abc``) has no section of its own in ``WHATS_NEW.md`` and
never will, so Help > What's new on the Dev app fell to the generic "Thanks for
updating" body. It now shows what the stable it is built on shows, with a line
above the notes saying so and linking the changelog for everything since.

The stable the builder picks is the newest final release at or below the dev
version's base, by rule rather than by name: a beta between the stable and the
base is not a stable, a section above the base belongs to a later release, and
``[Unreleased]`` is not a version. The stable build's own output is pinned
unchanged beside each of these.

Hermetic: the notes are passed in as text, and the dialog tests build the dialog
directly on the offscreen platform the suite runs under.
"""

import pytest

from PyReconstruct.modules.gui.main import first_launch as F


NOTES = """# What's New

## [Unreleased]

- Not shipped yet.

## [1.25.0] — 2026-11-20

- Ahead of this nightly's base.

## [1.24.0-beta-1] — 2026-10-01

- A beta is not a stable.

## [1.23.0] — 2026-09-27

- The latest stable.

## [1.22.3] — 2026-09-14

- The one before.

## [1.22.2] — 2026-08-28

- Two before.

## [1.22.1] — 2026-08-25

- Three before.
"""

NIGHTLY = "1.24.0.dev20261007"
SOURCE_CHECKOUT = "1.24.0.dev5+g0123abc"
STABLE = "1.23.0"


# ---- which section a dev build anchors on -----------------------------------
def test_latest_stable_section_skips_betas_unreleased_and_later_releases():
    sections = F.parse_all_sections(NOTES)
    picked = F.latest_stable_section(sections, NIGHTLY)
    assert picked["version"] == STABLE
    # the same answer however the dev version is spelled
    assert F.latest_stable_section(sections, SOURCE_CHECKOUT)["version"] == STABLE
    # nothing at or below the base -> None, never a guess
    assert F.latest_stable_section(sections, "1.22.0.dev1") is None
    assert F.latest_stable_section([], NIGHTLY) is None
    assert F.latest_stable_section(sections, "garbage") is None


def test_latest_stable_section_takes_a_section_landed_ahead_of_its_tag():
    """The notes for a release land on main before the tag; the next nightly
    carries them and should show them."""
    text = NOTES.replace("## [1.24.0-beta-1] — 2026-10-01", "## [1.24.0] — 2026-10-08")
    picked = F.latest_stable_section(F.parse_all_sections(text), NIGHTLY)
    assert picked["version"] == "1.24.0"


# ---- the builder on a dev build ---------------------------------------------
@pytest.mark.parametrize("dev", [NIGHTLY, SOURCE_CHECKOUT])
def test_dev_build_shows_the_latest_stable_notes_with_the_note_first(dev):
    c = F.whats_new_content(dev, on_demand=True, text=NOTES)
    assert c["version"] == dev                       # the header names what runs
    assert c["date"] is None                         # the date is the stable's; it is in the body
    assert c["orienter"] == "Recent releases"
    assert "### 1.23.0 — September 27, 2026" in c["body"]
    assert "The latest stable." in c["body"]
    assert "1.25.0" not in c["body"]
    assert "beta" not in c["body"]
    assert "Not shipped yet." not in c["body"]
    assert c["note"] is not None
    assert "1.23.0" in c["note"]
    assert f'href="{F.nightly_release_url(dev)}"' in c["note"]


@pytest.mark.parametrize("kwargs", [
    {"on_demand": True},
    {"last_seen": None, "installed_app": False},
    {"last_seen": None, "installed_app": True},
])
def test_dev_build_body_is_the_stable_builds_body(kwargs):
    """Whatever framing, the nightly lists exactly what the stable lists."""
    dev = F.whats_new_content(NIGHTLY, text=NOTES, cap=3, **kwargs)
    stable = F.whats_new_content(STABLE, text=NOTES, cap=3, **kwargs)
    assert dev["body"] == stable["body"]
    assert dev["truncated"] is stable["truncated"] is True   # four stables, cap of three
    assert dev["orienter"] == stable["orienter"]
    assert dev["byline"] == stable["byline"]
    assert dev["note"] is not None and stable["note"] is None


def test_dev_build_welcome_keeps_the_update_checks_note_under_the_notes():
    c = F.whats_new_content(NIGHTLY, last_seen=None, text=NOTES, installed_app=True)
    assert c["orienter"] == "Welcome to PyReconstruct"
    assert "The latest stable." in c["body"]
    assert "checks once a day" in c["body"]
    assert c["body"].index("The latest stable.") < c["body"].index("checks once a day")
    assert c["note"] is not None


@pytest.mark.parametrize("text", [
    NOTES.split("## [1.23.0]")[0],   # only Unreleased, 1.25.0 and the beta remain
    "",
])
def test_dev_build_with_no_stable_below_it_gets_the_generic_body(text):
    c = F.whats_new_content(NIGHTLY, on_demand=True, text=text)
    assert c["body"] == F.GENERIC_NOTES
    assert c["note"] is None
    assert c["date"] is None


# ---- the stable build is untouched ------------------------------------------
@pytest.mark.parametrize("version", [STABLE, "1.24.0b1"])
def test_stable_and_beta_builds_match_their_own_section_without_a_note(version):
    c = F.whats_new_content(version, on_demand=True, text=NOTES)
    assert c["note"] is None
    assert c["version"] == version
    assert f"### {F.parse_all_sections(NOTES)[0]['version']}" not in c["body"]   # not 1.25.0
    if version == STABLE:
        assert c["date"] == "September 27, 2026"
        assert "### 1.23.0 — September 27, 2026" in c["body"]
    else:
        assert c["date"] == "October 1, 2026"
        assert "A beta is not a stable." in c["body"]


def test_stable_build_after_an_update_is_unchanged():
    c = F.whats_new_content(STABLE, last_seen="1.22.2", text=NOTES)
    assert c["orienter"] == "What's new since 1.22.2"
    assert "The latest stable." in c["body"]
    assert "The one before." in c["body"]
    assert "Two before." not in c["body"]
    assert c["note"] is None


# ---- the note and the link ---------------------------------------------------
def test_dev_build_note_is_the_approved_text_with_one_link():
    note = F.dev_build_note("1.23.0", "https://example.test/releases/tag/v1.24.0.dev20261007")
    assert note == (
        "This is the nightly build. The notes below are for 1.23.0, the latest "
        "stable release. The latest PyReconstruct Dev changes can be found in "
        'the <a href="https://example.test/releases/tag/v1.24.0.dev20261007">live changelog</a>.'
    )
    assert note.count("<a ") == 1
    for dash in ("—", "–", "--"):
        assert dash not in note


def test_nightly_release_url_is_the_builds_own_page_or_the_index():
    """A nightly links its own release; a source checkout has none and gets the list."""
    from PyReconstruct.modules.backend.updater.updater import GITHUB_REPO
    assert F.nightly_release_url(NIGHTLY) == F.github_release_url(NIGHTLY)
    assert F.nightly_release_url(NIGHTLY) == (
        f"https://github.com/{GITHUB_REPO}/releases/tag/v{NIGHTLY}"
    )
    assert F.nightly_release_url("v" + NIGHTLY) == F.nightly_release_url(NIGHTLY)
    index = f"https://github.com/{GITHUB_REPO}/releases"
    assert F.nightly_release_url(SOURCE_CHECKOUT) == index   # +g local part: no release
    assert F.nightly_release_url("1.24.0.dev5") == index     # not a dated nightly tag
    assert F.nightly_release_url("1.24.0") == index          # not a dev version at all
    assert F.nightly_release_url(None) == index


# ---- the dialog --------------------------------------------------------------
@pytest.mark.gui
def test_dialog_renders_the_note_above_the_notes_on_a_dev_build(qapp):
    from PySide6.QtWidgets import QLabel
    from PyReconstruct.modules.gui.dialog import whats_new as W

    content = F.whats_new_content(NIGHTLY, on_demand=True, text=NOTES)
    dialog = W.WhatsNewDialog(None, NIGHTLY, content=content, url="https://example.test/releases")
    try:
        assert dialog._note is not None
        assert "nightly build" in dialog._note.text()
        assert f'href="{F.github_release_url(NIGHTLY)}"' in dialog._note.text()
        lay = dialog.layout()
        assert lay.indexOf(dialog._note) < lay.indexOf(dialog._notes)
        assert dialog._notes.toPlainText().lstrip().startswith("1.23.0")
        assert dialog.windowTitle() == f"What's new in PyReconstruct {NIGHTLY}"
        # no release-date line: the only italic labels are the orienter and the footer
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        assert not any("Released" in t for t in texts)
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.gui
def test_dialog_adds_no_note_widget_on_a_stable_build(qapp):
    from PySide6.QtWidgets import QLabel
    from PyReconstruct.modules.gui.dialog import whats_new as W

    content = F.whats_new_content(STABLE, on_demand=True, text=NOTES)
    dialog = W.WhatsNewDialog(None, STABLE, content=content, url="https://example.test/releases")
    try:
        assert dialog._note is None
        texts = [label.text() for label in dialog.findChildren(QLabel)]
        assert not any("nightly build" in t for t in texts)
        assert any("Released" in t for t in texts)   # inside its color span
    finally:
        dialog.close()
        dialog.deleteLater()

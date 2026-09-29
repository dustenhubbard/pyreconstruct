"""The Windows uninstaller removes files an in-place update brought in.

Inno Setup's uninstaller deletes only what its own install log lists. An
in-place update swaps in a newer install folder without the installer, so any
file that is new in that tree is unknown to the log and would survive an
uninstall. ``[UninstallDelete]`` removes the PyInstaller payload
(``_internal``) and the updater's folder (``_updater``) outright.

The two AppIds are pinned here too. The in-place updater will find a Windows
install through its uninstall registry key, which Inno Setup names after the
AppId ('{A1B2C3D4-...}_is1'; the doubled brace in the script is an escape), so
a changed AppId would cut every existing install off from in-place updates.
"""
import re
from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "PyReconstruct.iss"

STABLE_APPID = "{{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C}}"
DEV_APPID = "{{0C76AF3D-BB20-4EDB-99FC-2B9244E213F7}}"


def _sections(text):
    """{section name: [entry lines]} with comments, blanks, and preprocessor lines dropped."""
    sections, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def _entry(line):
    """'Type: x; Name: "y"' -> {'type': 'x', 'name': 'y'}."""
    fields = {}
    for part in line.split(";"):
        key, sep, value = part.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip().strip('"')
    return fields


def test_uninstall_deletes_the_payload_and_the_updater_folder():
    entries = [_entry(line) for line in _sections(ISS.read_text(encoding="utf-8")).get("UninstallDelete", [])]
    targets = {(e.get("type"), e.get("name")) for e in entries}

    assert ("filesandordirs", r"{app}\_internal") in targets
    assert ("filesandordirs", r"{app}\_updater") in targets


STAGING = "{app}\\..\\.{#PYR_NAME}-update"


def test_uninstall_delete_stays_inside_the_install_folder():
    """A filesandordirs entry outside {app} could delete user data.

    The one exception is the updater's staging folder beside the install,
    named for this app alone.
    """
    entries = [_entry(line) for line in _sections(ISS.read_text(encoding="utf-8")).get("UninstallDelete", [])]

    assert entries
    for e in entries:
        if e["name"] == STAGING:
            continue
        assert e["name"].startswith("{app}\\"), e
        assert e["name"] != "{app}\\", e
        assert ".." not in e["name"], e


def test_uninstall_removes_the_staging_folder_the_helper_uses():
    """The name the helper insists on for its staging folder, beside the install."""
    entries = [_entry(line) for line in _sections(ISS.read_text(encoding="utf-8")).get("UninstallDelete", [])]
    assert ("filesandordirs", STAGING) in {(e.get("type"), e.get("name")) for e in entries}

    apply_py = (ISS.parents[2] / "PyReconstruct" / "modules" / "backend" / "updater" / "apply.py").read_text()
    assert "os.path.basename(staging) != f\".{plan['app_name']}-update\"" in apply_py


def test_the_two_appids_are_unchanged():
    text = ISS.read_text(encoding="utf-8")
    appids = re.findall(r'#define\s+PYR_APPID\s+"([^"]+)"', text)

    assert appids == [DEV_APPID, STABLE_APPID]
    assert "AppId={#PYR_APPID}" in _sections(text)["Setup"]

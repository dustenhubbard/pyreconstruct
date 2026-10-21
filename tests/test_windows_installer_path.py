"""The Windows installer puts {app}\\bin on the user's PATH, and only that.

The terminal commands live in {app}\\bin. PATH is a value the user owns, so
the script never deletes it (no ``uninsdeletevalue``, no ``RegDeleteValue``),
never rewrites it through ``setx`` (which truncates long values), and touches
it only in [Code], where install adds the one entry if it is missing and
uninstall removes exactly that entry. ``ChangesEnvironment`` makes Setup tell
Explorer, so a new terminal sees the change. Read as text, as in
test_windows_uninstall_removes_update_files.py.
"""

import re
from pathlib import Path

from test_windows_uninstall_removes_update_files import ISS, _entry, _sections


def _text():
    return ISS.read_text(encoding="utf-8")


def _code():
    text = _text()
    return text[text.index("[Code]"):]


def _function(code, header):
    start = code.index(header)
    end = code.find("\nend;", start)
    return code[start:end]


def test_setup_announces_the_environment_change():
    assert "ChangesEnvironment=yes" in _sections(_text())["Setup"]


def test_path_is_never_deleted_or_set_wholesale():
    text = _text()
    for line in _sections(text).get("Registry", []):
        e = _entry(line)
        assert e.get("subkey", "").lower() != "environment", line
        assert e.get("valuename", "").lower() != "path", line
    assert not re.search(r"uninsdeletevalue[^\n]*Path|Path[^\n]*uninsdeletevalue", text, re.I)
    assert "setx" not in text.lower()
    assert "RegDeleteValue" not in text


def test_only_the_bin_folder_goes_on_path():
    code = _code()
    assert "Result := AddBackslash(RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) + 'bin';" in code
    writes = re.findall(r"RegWrite\w+\(([^;]*)\);", code)
    assert writes, "the script writes PATH somewhere"
    for args in writes:
        assert args.startswith("HKCU, EnvKey, 'Path'"), args
    assert "EnvKey = 'Environment';" in code


def test_install_adds_the_entry_once():
    code = _code()
    add = _function(code, "procedure AddCommandsToPath")
    assert "if PathHasEntry(Value, CommandsDir()) then\n    exit;" in add
    assert "RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Value + CommandsDir());" in add
    step = _function(code, "procedure CurStepChanged")
    assert re.search(r"if CurStep = ssPostInstall then\s+AddCommandsToPath\(\);", step)


def test_uninstall_removes_exactly_that_entry():
    code = _code()
    remove = _function(code, "procedure RemoveCommandsFromPath")
    assert "if not SamePathEntry(Parts[I], CommandsDir()) then" in remove
    assert "RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Kept);" in remove
    step = code[code.index("procedure CurUninstallStepChanged"):]
    assert re.search(r"if CurUninstallStep = usUninstall then\s+RemoveCommandsFromPath\(\);", step)


def test_entries_compare_without_case_or_a_trailing_backslash():
    same = _function(_code(), "function SamePathEntry")
    assert "RemoveBackslashUnlessRoot(RemoveQuotes(Trim(A)))" in same
    assert "RemoveBackslashUnlessRoot(RemoveQuotes(Trim(B)))" in same
    assert "CompareText(A, B) = 0" in same  # CompareText ignores case


def test_uninstall_removes_the_commands_folder_an_update_brought_in():
    entries = [_entry(line) for line in _sections(_text()).get("UninstallDelete", [])]
    assert ("filesandordirs", r"{app}\bin") in {(e.get("type"), e.get("name")) for e in entries}


def test_the_app_side_uses_the_same_folder():
    """The launch-time add (cli_commands.windows_bin_dir) and the installer
    name the same folder beside the exe."""
    src = (Path(ISS).parents[2] / "PyReconstruct" / "modules" / "backend" / "func" / "cli_commands.py").read_text()
    assert 'bin_dir = folder / "bin"' in src

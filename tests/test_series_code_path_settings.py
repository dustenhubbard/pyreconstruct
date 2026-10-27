"""A series code that reads as a path keeps settings of its own.

A series' own settings live in the domain ``KHLab / PyReconstruct-<code>``. In
the Ini format (Linux, and this suite) that name becomes a file path, so a
code with an empty, "." or ".." segment between two slashes resolves to
another file: ``a//b`` and ``a/./b`` to the file of ``a/b``, and
``/../PyReconstruct-existing`` to the file of ``existing``. Such a code now
names the domain ``<app> PATH-<SHA-256 of the code>``. Every other code,
``a/b`` included, names the same domain as before.

The settings reads and writes run in a child process with the suite's
settings isolation, which puts every `QSettings` under a temporary Ini root
inside `tmp_path`.
"""
import ast
import itertools
import os
import re

import pytest
from PySide6.QtCore import QDir

from PyReconstruct.modules.constants import settings_domain as SD
from test_series_code_nul_settings import APPS, PRELUDE, _digest, _run

PATH_CODES = [
    "/../PyReconstruct-existing", "x/../PyReconstruct-existing",
    "/../PyReconstruct Dev-existing", "/../PyReconstruct", "a/x/../b",
    "a/./b", "x/./y/z", "/./x", "a//b", "//a/b", "a/../", "//",
]

PLAIN_CODES = [
    "existing", "a/b", "x/y/z", "/existing", "/a/b", "/", "a/", ".", "..",
    "...", "./a/b", "../x", "x/..", "a/.", "/..", "a/.../b", "a/..b/c",
    ".a/b", "a\\b", "\\..\\PyReconstruct-existing", "a\\.\\b",
    "x\\../PyReconstruct-existing",
]


def _apart(existing_name, incoming_code):
    """Another domain has its backups set first. The incoming series then
    reads and sets its own."""
    return PRELUDE + f"""
existing = QSettings("KHLab", {existing_name!r})
existing.setValue("backup_dir", "/existing-series-backups")
existing.sync()
incoming = series({incoming_code!r})
before = incoming.getOption("backup_dir")
incoming.setOption("backup_dir", "/incoming-series-backups")
existing = QSettings("KHLab", {existing_name!r})
print(repr([
    before,
    existing.value("backup_dir", "", str),
    series({incoming_code!r}).getOption("backup_dir"),
    where({existing_name!r}),
    store._settings({incoming_code!r}).fileName(),
]))
"""


@pytest.mark.parametrize("existing_name, incoming_code", [
    ("PyReconstruct-existing", "/../PyReconstruct-existing"),
    ("PyReconstruct-existing", "x/../PyReconstruct-existing"),
    ("PyReconstruct Dev-existing", "/../PyReconstruct Dev-existing"),
    ("PyReconstruct", "/../PyReconstruct"),
    ("PyReconstruct-a/b", "a/./b"),
    ("PyReconstruct-a/b", "a//b"),
    ("PyReconstruct-a/b", "a/x/../b"),
])
def test_a_path_code_leaves_another_domain_its_backups(
    tmp_path, existing_name, incoming_code
):
    before, existing, incoming, existing_at, incoming_path = ast.literal_eval(
        _run(_apart(existing_name, incoming_code), tmp_path)
    )
    assert before == ""
    assert existing == "/existing-series-backups"
    assert incoming == "/incoming-series-backups"
    # the incoming series' file sits in the settings folder, under its own name
    folder = existing_at[0]
    if "/" in existing_name:
        folder = os.path.dirname(folder)
    assert incoming_path == os.path.join(
        folder, f"PyReconstruct PATH-{_digest(incoming_code)}.ini"
    )


@pytest.mark.parametrize("code, neighbor", [
    ("a/b", "a"), ("a/b", "b"), ("/existing", "existing"), ("x/..", "x"),
])
def test_a_plain_code_keeps_its_own_file(tmp_path, code, neighbor):
    # a code with a slash and no such segment gets its own file in a subfolder
    before, existing, incoming, existing_at, incoming_path = ast.literal_eval(
        _run(_apart(f"PyReconstruct-{neighbor}", code), tmp_path)
    )
    assert before == ""
    assert existing == "/existing-series-backups"
    assert incoming == "/incoming-series-backups"
    assert incoming_path == os.path.join(existing_at[0], f"PyReconstruct-{code}.ini")


@pytest.mark.parametrize("code", PATH_CODES)
@pytest.mark.parametrize("app", APPS)
def test_a_path_code_names_its_digest(app, code):
    assert SD.series_app(app, code) == f"{app} PATH-{_digest(code)}"


@pytest.mark.parametrize("code", PLAIN_CODES)
@pytest.mark.parametrize("app", APPS)
def test_a_plain_code_names_the_same_domain(app, code):
    # the name every release before this one built
    assert SD.series_app(app, code) == app + "-" + code


def test_a_nul_code_keeps_its_nul_name():
    code = "\0/../PyReconstruct-existing"
    assert SD.series_app("PyReconstruct", code) == f"PyReconstruct NUL-{_digest(code)}"


def test_every_short_code_names_a_file_of_its_own():
    # every code up to five characters over a mix of plain, path and NUL; the
    # two app-wide domains are in the set too
    root = "/settings/KHLab/"
    files = {}
    for app in APPS:
        files[root + app + ".ini"] = (app, None)
    alphabet = ["a", "-", "/", "\\", ".", "\0"]
    for n in range(6):
        for chars in itertools.product(alphabet, repeat=n):
            code = "".join(chars)
            for app in APPS:
                name = SD.series_app(app, code)
                assert "\0" not in name
                path = root + name + ".ini"
                # Qt resolves nothing in the path, so it names this file alone
                assert QDir.cleanPath(path) == path, (app, code)
                assert re.match(re.escape(app) + "(-| NUL-| PATH-)", name)
                assert files.setdefault(path, (app, code)) == (app, code), path

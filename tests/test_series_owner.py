"""The "series in use" guard names which app holds the series.

The guard mechanism is the heartbeat file the field widget refreshes every
five seconds; it has refused concurrent opens for a long time. What is new is
identity: with the stable and Dev builds installable side by side, "another
window" is no longer a useful answer, so an owner file written beside the
heartbeat lets the message say "PyReconstruct Dev" (or the host, when the
series lives on a share opened from another machine).
"""
import json
import os
import socket

import pytest

from PyReconstruct.modules.datatypes.series_owner import (
    OWNER_FILENAME,
    app_display_name,
    describe_owner,
    read_owner,
    write_owner,
)


def test_write_and_read_round_trip(tmp_path):
    write_owner(str(tmp_path))
    owner = read_owner(str(tmp_path))
    assert owner["app"] == "PyReconstruct"
    assert owner["pid"] == os.getpid()
    assert owner["host"] == socket.gethostname()


def test_the_dev_build_names_itself(tmp_path, monkeypatch):
    """Packaging sets PYRECON_APP_NAME; the message must carry it through."""
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    assert app_display_name() == "PyReconstruct Dev"
    write_owner(str(tmp_path))
    assert describe_owner(read_owner(str(tmp_path))) == "PyReconstruct Dev"


def test_missing_or_broken_owner_falls_back_to_the_old_wording(tmp_path):
    """Identity is a courtesy, never a gate: no file, garbage, or wrong type
    all degrade to the message the guard has always shown."""
    assert describe_owner(read_owner(str(tmp_path))) == "another window"

    (tmp_path / OWNER_FILENAME).write_text("{not json")
    assert describe_owner(read_owner(str(tmp_path))) == "another window"

    (tmp_path / OWNER_FILENAME).write_text('["a", "list"]')
    assert describe_owner(read_owner(str(tmp_path))) == "another window"


def test_a_remote_holder_is_named_with_its_host(tmp_path):
    """A series on a network share can be held by another machine, where a
    pid means nothing; the host is what the user can act on."""
    (tmp_path / OWNER_FILENAME).write_text(
        json.dumps({"app": "PyReconstruct", "pid": 1, "host": "other-machine"})
    )
    assert describe_owner(read_owner(str(tmp_path))) == "PyReconstruct on other-machine"


def test_write_failure_is_swallowed(tmp_path):
    """A read-only working dir must not break opening the series."""
    target = tmp_path / "ro"
    target.mkdir()
    os.chmod(target, 0o555)
    try:
        write_owner(str(target))   # must not raise
        assert read_owner(str(target)) is None
    finally:
        os.chmod(target, 0o755)


def test_field_widget_writes_the_owner_beside_the_heartbeat(main_window):
    """End to end: opening a series leaves both files in the working dir."""
    wdir = main_window.series.getwdir()
    names = os.listdir(wdir)
    assert OWNER_FILENAME in names, names
    assert any(n.isnumeric() for n in names), "the heartbeat itself is gone?"
    owner = read_owner(wdir)
    assert owner["pid"] == os.getpid()

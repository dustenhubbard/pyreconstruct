"""The command-line entry point takes a jser path positionally.

``pyreconstruct series.jser`` is what a shell user types and what a desktop
entry's ``%f`` produces. The entry point only understood ``-f series.jser``, so
the Linux installer's generated launcher carried a shim that rewrote a single
non-flag argument into ``-f``. The shim stays for the launchers already on
disk; this pins the entry point itself understanding both.

Also pins the missing-path behavior. ``MainWindow.__init__`` opens the welcome
series for a filename that does not exist, so a typo used to produce a launched
app with no series and nothing said about it. The CLI now reports it and exits
non-zero, before Qt starts.

No Qt anywhere in here: ``open_file`` imports ``PyReconstruct.run`` lazily, and
every test either stops before that import or replaces the module.
"""

import argparse
import sys
import types

import pytest

from PyReconstruct import cli


@pytest.fixture
def jser(tmp_path):
    """A real file on disk, since the CLI now checks that the path exists."""
    p = tmp_path / "series.jser"
    p.write_text("{}")
    return p


@pytest.fixture
def opened(monkeypatch):
    """Record what ``main`` hands to ``open_file`` instead of launching."""
    seen = []
    monkeypatch.setattr(cli, "open_file", seen.append)
    return seen


def run_cli(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pyreconstruct"] + argv)
    cli.main()


# ---- the positional argument -------------------------------------------------

def test_a_positional_path_is_the_file_to_open(jser, opened, monkeypatch):
    run_cli([str(jser)], monkeypatch)
    assert opened == [str(jser)]


def test_the_f_flag_still_works(jser, opened, monkeypatch):
    run_cli(["-f", str(jser)], monkeypatch)
    assert opened == [str(jser)]


def test_the_long_filename_flag_still_works(jser, opened, monkeypatch):
    run_cli(["--filename", str(jser)], monkeypatch)
    assert opened == [str(jser)]


def test_no_argument_still_opens_the_welcome_series(opened, monkeypatch):
    run_cli([], monkeypatch)
    assert opened == [None]


def test_a_relative_positional_path_is_passed_through_unchanged(jser, opened, monkeypatch):
    """The CLI must not resolve or normalize the path it was given.

    ``MainWindow`` stores ``series.jser_fp`` from this string and the recents
    list is built from it, so rewriting the path here would put a different
    string into the user's recents than the one they typed.
    """
    monkeypatch.chdir(jser.parent)
    run_cli(["series.jser"], monkeypatch)
    assert opened == ["series.jser"]


# ---- the two forms together --------------------------------------------------

def test_the_same_file_named_both_ways_is_accepted(jser, opened, monkeypatch):
    """The installer's launcher shim plus a shell alias could produce this."""
    run_cli([str(jser), "-f", str(jser)], monkeypatch)
    assert opened == [str(jser)]


def test_two_different_files_is_an_error_not_a_silent_choice(tmp_path, opened, monkeypatch):
    a = tmp_path / "a.jser"
    b = tmp_path / "b.jser"
    a.write_text("{}")
    b.write_text("{}")
    with pytest.raises(SystemExit) as exc:
        run_cli([str(a), "-f", str(b)], monkeypatch)
    assert exc.value.code == 2          # argparse's usage-error code
    assert opened == []                 # nothing was opened


def test_resolve_reports_the_conflict_through_the_parser():
    """The refusal goes through ``parser.error``, so it prints usage."""
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(path="one.jser", filename="two.jser")
    with pytest.raises(SystemExit):
        cli.resolve_jser_path(parser, args)


def test_resolve_prefers_the_positional_when_both_name_one_file():
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(path="s.jser", filename="s.jser")
    assert cli.resolve_jser_path(parser, args) == "s.jser"


# ---- the other flags are undisturbed -----------------------------------------

def test_version_still_wins_over_a_positional(jser, opened, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_version_string", lambda: "9.9.9")
    run_cli(["-V", str(jser)], monkeypatch)
    assert capsys.readouterr().out.strip() == "9.9.9"
    assert opened == []


def test_update_still_wins_over_a_positional(jser, opened, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_run_update", lambda *a: called.append(a))
    run_cli(["-u", str(jser)], monkeypatch)
    assert called and opened == []


def test_switch_still_takes_its_own_value(opened, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_run_update", lambda *a: called.append(a))
    run_cli(["-s", "main"], monkeypatch)
    assert called == [("main",)]
    assert opened == []


# ---- a path that does not exist ----------------------------------------------

def test_a_missing_path_is_reported_and_exits_nonzero(tmp_path, capsys):
    missing = tmp_path / "typo.jser"
    with pytest.raises(SystemExit) as exc:
        cli.open_file(str(missing))
    assert exc.value.code == 1
    assert "File not found" in capsys.readouterr().out


def test_a_missing_path_never_reaches_the_gui(tmp_path, monkeypatch):
    """The check runs before ``PyReconstruct.run`` is imported."""
    stub = types.ModuleType("PyReconstruct.run")
    stub.runPyReconstruct = lambda *a: pytest.fail("the GUI was launched")
    monkeypatch.setitem(sys.modules, "PyReconstruct.run", stub)
    with pytest.raises(SystemExit):
        cli.open_file(str(tmp_path / "typo.jser"))


def test_an_existing_path_reaches_the_gui(jser, monkeypatch):
    seen = []
    stub = types.ModuleType("PyReconstruct.run")
    stub.runPyReconstruct = seen.append
    monkeypatch.setitem(sys.modules, "PyReconstruct.run", stub)
    cli.open_file(str(jser))
    assert seen == [str(jser)]


def test_no_filename_reaches_the_gui_as_none(monkeypatch):
    """The welcome-series launch must not be caught by the existence check."""
    seen = []
    stub = types.ModuleType("PyReconstruct.run")
    stub.runPyReconstruct = seen.append
    monkeypatch.setitem(sys.modules, "PyReconstruct.run", stub)
    cli.open_file(None)
    assert seen == [None]


# ---- the entry point is declared ---------------------------------------------

def test_the_console_script_points_at_this_main():
    """``[project.scripts]`` in pyproject.toml names ``PyReconstruct.cli:main``."""
    import re
    from pathlib import Path as P

    pyproject = P(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = re.search(
        r"^\[project\.scripts\]\n(.*?)(?=^\[|\Z)",
        pyproject.read_text(),
        re.S | re.M,
    )
    assert scripts is not None
    assert "PyReconstruct.cli:main" in scripts.group(1)

"""``install_module``'s advice when the environment has no pip in it at all.

This project's documented from-source setup is ``uv sync`` (see README), and a
uv-created environment has no pip inside it -- uv installs packages itself and
does not need one. Verified on the environment this suite runs in: ``.venv/bin``
contains no ``pip``, ``importlib.util.find_spec("pip")`` is ``None``, and
``.venv/bin/python -m pip install <anything>`` exits 1 with "No module named
pip". Whatever spelling the install command uses, it cannot work there.

That made the in-app "this feature needs another package, shall I install it?"
offer end in the generic failure notice, whose whole content is "Please try pip
installing X in a terminal" -- which names the one command already established
not to exist, and sends a uv user to look for a problem in their network or
their permissions. The correct answer for them is ``uv add X`` or ``uv pip
install X``.

Three things are pinned here.

The first is the discrimination. Only a *missing pip* gets the new message. A
network timeout and a package that is not on the index both leave pip reachable
and both keep the generic notice, which is honest advice for them: running
``pip install`` again in a terminal is exactly what those need. The reason is
established by asking whether a pip exists rather than by matching the
subprocess output, because the two failures do not look alike -- a shell ``pip
install`` exits 127 with "pip: command not found", ``sys.executable -m pip``
exits 1 with "No module named pip" -- and a string match would pin the branch
to one spelling of the install command.

The second is the environment detection. uv stamps ``uv = <version>`` into the
environment's ``pyvenv.cfg`` and neither ``venv`` nor ``virtualenv`` writes that
key, so it is read directly rather than inferred from a directory called
``.venv``. A uv environment is not always named that (UV_PROJECT_ENVIRONMENT
renames it) and a directory with that name was not necessarily made by uv.

The third is that every command the notice prints can be copied verbatim and
will do what it says. Two ways that can fail, and both are asserted against.
The non-uv branch names an interpreter and must then spell its commands
``"<that interpreter>" -m ...``: bare ``python``/``pip`` resolve off PATH, and
this branch fires *because* PATH has no pip for the named interpreter, so a
bare token is guaranteed to point somewhere else. And the uv branch offers two
routes that differ in durability, so it has to say so -- a ``uv pip install``
is unrecorded and the next ``uv sync`` removes it again, which is measurable on
this project and which the README's own instructions will eventually trigger.
"""

import sys

import pytest

from PyReconstruct.modules.backend.imports import mod_imports


@pytest.fixture
def notes(monkeypatch):
    """Collect the modal notices instead of putting them on a screen."""

    seen = []
    monkeypatch.setattr(mod_imports, "note", seen.append)
    return seen


def _pip_absent(monkeypatch):
    """Neither route to a pip exists: not importable, not on PATH."""

    monkeypatch.setattr(mod_imports.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: None)


def _pip_present(monkeypatch):
    """A pip is on PATH, so a failed install has some other cause."""

    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: "/usr/bin/pip")


def _failing_install(monkeypatch, returncode, stderr):
    """Stand in for the pip subprocess, which must not actually run."""

    class _Completed:
        pass

    _Completed.returncode = returncode
    _Completed.stdout = ""
    _Completed.stderr = stderr

    monkeypatch.setattr(mod_imports.subprocess, "run", lambda *a, **k: _Completed())


def _environment_is(monkeypatch, tmp_path, pyvenv_cfg):
    """Point ``sys.prefix`` at a directory holding this ``pyvenv.cfg``.

    ``pyvenv_cfg`` of ``None`` writes no file at all, which is what a system
    interpreter and a frozen build both look like.
    """

    prefix = tmp_path / "prefix"
    prefix.mkdir()

    if pyvenv_cfg is not None:
        (prefix / "pyvenv.cfg").write_text(pyvenv_cfg, encoding="utf-8")

    monkeypatch.setattr(sys, "prefix", str(prefix))


UV_PYVENV_CFG = (
    "home = /Users/someone/.local/share/uv/python/cpython-3.11-macos-aarch64-none/bin\n"
    "implementation = CPython\n"
    "uv = 0.11.28\n"
    "version_info = 3.11\n"
    "include-system-site-packages = false\n"
    "prompt = pyreconstruct\n"
)

STDLIB_PYVENV_CFG = (
    "home = /opt/homebrew/opt/python@3.11/bin\n"
    "include-system-site-packages = false\n"
    "version = 3.11.15\n"
    "executable = /opt/homebrew/opt/python@3.11/bin/python3.11\n"
    "command = /opt/homebrew/opt/python@3.11/bin/python3.11 -m venv /tmp/env\n"
)


## ---------------------------------------------------------------------------
## The environment detector
## ---------------------------------------------------------------------------


def test_uv_marker_in_pyvenv_cfg_is_recognised(monkeypatch, tmp_path):
    """The `uv = <version>` key uv writes, and nothing else, is the signal."""

    _environment_is(monkeypatch, tmp_path, UV_PYVENV_CFG)
    assert mod_imports.uv_created_environment() is True


def test_a_stdlib_venv_is_not_mistaken_for_a_uv_one(monkeypatch, tmp_path):
    """`python -m venv` writes no `uv` key, so it must not match."""

    _environment_is(monkeypatch, tmp_path, STDLIB_PYVENV_CFG)
    assert mod_imports.uv_created_environment() is False


def test_no_pyvenv_cfg_is_not_a_uv_environment(monkeypatch, tmp_path):
    """A system interpreter or a frozen build has no pyvenv.cfg to read."""

    _environment_is(monkeypatch, tmp_path, None)
    assert mod_imports.uv_created_environment() is False


def test_a_directory_named_dot_venv_is_not_the_signal(monkeypatch, tmp_path):
    """Detection reads the marker, not the directory name.

    The tempting shortcut -- "`.venv` in `sys.prefix`" -- is wrong in both
    directions. This is the false-positive half: a plain `python -m venv .venv`
    is the README's own documented alternative to uv, and telling that user to
    run `uv add` would be exactly the kind of unusable advice this change
    exists to remove.
    """

    prefix = tmp_path / ".venv"
    prefix.mkdir()
    (prefix / "pyvenv.cfg").write_text(STDLIB_PYVENV_CFG, encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(prefix))

    assert mod_imports.uv_created_environment() is False


def test_a_uv_environment_under_another_name_still_matches(monkeypatch, tmp_path):
    """And the false-negative half: UV_PROJECT_ENVIRONMENT renames `.venv`."""

    prefix = tmp_path / "some-other-env"
    prefix.mkdir()
    (prefix / "pyvenv.cfg").write_text(UV_PYVENV_CFG, encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(prefix))

    assert mod_imports.uv_created_environment() is True


## ---------------------------------------------------------------------------
## The message
## ---------------------------------------------------------------------------


def test_uv_environment_without_pip_is_told_to_use_uv(monkeypatch, tmp_path, notes):
    """The case this change exists for, end to end through `install_module`.

    A uv-created environment, no pip anywhere, a failed install. The notice
    must name the uv commands that work and must not repeat the `pip install`
    advice that cannot.
    """

    _environment_is(monkeypatch, tmp_path, UV_PYVENV_CFG)
    _pip_absent(monkeypatch)
    _failing_install(monkeypatch, 127, "/bin/sh: pip: command not found\n")

    assert mod_imports.install_module("svgwrite") is False

    assert len(notes) == 1
    message = notes[0]

    assert "uv add svgwrite" in message
    assert "uv pip install svgwrite" in message
    assert "no pip in it" in message
    assert "created by uv" in message
    assert "Then restart PyReconstruct." in message

    ## The two routes are not equivalent and the difference is not obvious, so
    ## the notice has to state it rather than leave it to be discovered. `uv
    ## add` records the package in pyproject.toml and uv.lock; `uv pip install`
    ## does not, and an unrecorded package is *removed* by the next `uv sync`
    ## -- measured on this project, where `uv sync --frozen --no-default-groups
    ## --extra test` after a `uv pip install roifile` prints `Uninstalled 1
    ## package - roifile`. Saying only "without recording it" leaves the reader
    ## to infer that consequence, and the README tells them to run `uv sync`.
    assert "survives later syncs" in message
    assert "the next `uv sync` removes it again" in message

    ## The old advice, in either of its forms, must be gone: it is the thing
    ## being fixed. "Something went wrong" said nothing at all, and "try pip
    ## installing it in a terminal" named a command that does not exist here.
    assert "Something went wrong" not in message
    assert "try pip installing" not in message
    assert "ensurepip" not in message


def test_no_pip_outside_a_uv_environment_gets_the_pip_route(
    monkeypatch, tmp_path, notes
):
    """Not every pip-less interpreter is uv's, and that one needs pip itself.

    Here the remedy really is to obtain a pip -- `ensurepip` -- and the uv
    command is offered as the alternative rather than as the answer.
    """

    _environment_is(monkeypatch, tmp_path, STDLIB_PYVENV_CFG)
    _pip_absent(monkeypatch)
    _failing_install(monkeypatch, 1, "python: No module named pip\n")

    assert mod_imports.install_module("svgwrite") is False

    assert len(notes) == 1
    message = notes[0]

    assert "pip is not available" in message
    assert "uv pip install svgwrite" in message

    ## Names which interpreter has no pip. Without it the user cannot tell
    ## which of several environments the advice applies to.
    assert sys.executable in message

    ## And the commands must target *that* interpreter, not a bare token. This
    ## branch fires only when `pip_is_reachable()` is False, which requires
    ## `shutil.which("pip")` to be None -- so by construction PATH does not
    ## lead back to the interpreter just named. `python -m ensurepip` typed
    ## into a fresh terminal would add pip to, and `pip install` would install
    ## the package into, whichever environment PATH happens to resolve: the
    ## right-looking-command-wrong-target failure this whole notice exists to
    ## remove, one branch over. Quoted so a path with spaces survives.
    assert f'"{sys.executable}" -m ensurepip --upgrade' in message
    assert f'"{sys.executable}" -m pip install svgwrite' in message

    ## The bare forms must be gone. Anchored to the newline-plus-indent the
    ## command block uses, so these cannot be satisfied by the prose that
    ## explains why bare tokens are wrong, nor by the `uv pip install`
    ## alternative offered at the end.
    assert "\n    python -m ensurepip" not in message
    assert "\n    pip install svgwrite" not in message

    assert "Something went wrong" not in message
    assert "try pip installing" not in message

    ## The uv-specific instruction has no business here: `uv add` edits
    ## pyproject.toml and uv.lock, which is not what a stdlib venv wants.
    assert "uv add" not in message


def test_the_message_names_the_pip_name_not_the_import_name(
    monkeypatch, tmp_path, notes
):
    """`cloudvolume` is installed as `cloud-volume`, and the user has to type it.

    `modules_available` already carries that mapping into `install_module` as a
    tuple. The command lines in the notice are meant to be copied verbatim, so
    they have to carry the install name -- `uv add cloudvolume` fails.
    """

    _environment_is(monkeypatch, tmp_path, UV_PYVENV_CFG)
    _pip_absent(monkeypatch)
    _failing_install(monkeypatch, 127, "/bin/sh: pip: command not found\n")

    assert mod_imports.install_module(("cloudvolume", "cloud-volume")) is False

    message = notes[0]
    assert "uv add cloud-volume" in message
    assert "uv pip install cloud-volume" in message
    assert "uv add cloudvolume" not in message


## ---------------------------------------------------------------------------
## What must NOT change
## ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: Could not find a version that satisfies the requirement svgwrite\n",
        "WARNING: Retrying ... after connection broken by NewConnectionError\n",
        "ERROR: Could not install packages due to an OSError: [Errno 13] Permission denied\n",
    ],
    ids=["not-on-index", "network", "permissions"],
)
def test_ordinary_install_failures_keep_the_generic_advice(
    monkeypatch, tmp_path, notes, stderr
):
    """Pip ran and pip failed. Retrying it in a terminal is real advice.

    The guard against over-reach: the new branch must fire on a missing pip
    only. Claiming "this environment has no pip" to a user whose index lookup
    404'd would be a new wrong message replacing the old one.
    """

    _environment_is(monkeypatch, tmp_path, UV_PYVENV_CFG)
    _pip_present(monkeypatch)
    _failing_install(monkeypatch, 1, stderr)

    assert mod_imports.install_module("svgwrite") is False

    assert len(notes) == 1
    message = notes[0]

    assert message == (
        "Something went wrong. Please try pip installing svgwrite in a terminal."
    )
    assert "uv add" not in message


def test_a_successful_install_is_unaffected(monkeypatch, tmp_path, notes):
    """The pip-absence probe sits in the failure branch and nowhere else.

    Belt and braces on placement: an environment that reports no pip but whose
    install command somehow succeeded (a wrapper, a frozen build shelling out
    elsewhere) must still get the success notice, not a lecture about uv.
    """

    _environment_is(monkeypatch, tmp_path, UV_PYVENV_CFG)
    _pip_absent(monkeypatch)
    _failing_install(monkeypatch, 0, "")

    ## `json` stands in for the just-installed package: `install_module` imports
    ## it to report where it landed, so it has to be genuinely importable.
    assert mod_imports.install_module("json") is True

    assert len(notes) == 1
    assert "successfully installed" in notes[0]
    assert "uv add" not in notes[0]


def test_pip_on_path_alone_counts_as_reachable(monkeypatch):
    """Either route to a pip is enough; the claim needs both to be absent.

    A frozen build can have a `pip` on PATH with no importable `pip` module,
    and the reverse holds inside an environment whose `bin` is not on PATH.
    Telling either of those users there is no pip would be false.
    """

    monkeypatch.setattr(mod_imports.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: "/usr/bin/pip")
    assert mod_imports.pip_is_reachable() is True

    monkeypatch.setattr(
        mod_imports.importlib.util, "find_spec", lambda name: object()
    )
    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: None)
    assert mod_imports.pip_is_reachable() is True

    _pip_absent(monkeypatch)
    assert mod_imports.pip_is_reachable() is False

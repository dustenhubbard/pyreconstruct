"""Regression tests for ``install_module`` installing into the wrong Python.

``install_module`` shelled out to a bare ``pip`` --
``subprocess.run(f"pip install {name}", shell=True)`` -- and on ``returncode ==
0`` called ``module_path``, whose unguarded ``__import__`` runs *in this
process*. Those two are not the same interpreter. A bare ``pip`` resolves off
``PATH``, and on any machine with more than one Python on it (a system Python
next to a venv, conda next to homebrew, and always in a frozen bundle, which
carries no ``pip`` of its own) it can install into a different environment
entirely. pip then reports success, ``module_path``'s import raises
``ModuleNotFoundError``, and nothing caught it: the exception left
``install_module`` for ``customExcepthook``. ``packaging/PyReconstruct.spec``
builds with ``console=False``, so a Windows user got no console and no
traceback -- the app either showed a crash dialog for something they could not
act on, or nothing at all.

The obvious repair -- swap ``pip`` for ``sys.executable -m pip`` -- is right for
a source install and *wrong* for the frozen build it was aimed at, which is why
the frozen case is handled separately rather than by the same line. In a
PyInstaller bundle ``sys.executable`` is the app's own launcher, not a Python
interpreter, and the bootloader does not interpret ``-m``: it passes it through
as ``sys.argv``. Measured on a one-folder build of a probe script, the child
process was a second copy of the application, which ``capture_output=True``
waits on until it exits and which then exits ``0``. That turns a conditional
crash into an unconditional hang plus a bogus "successfully installed". So a
frozen bundle does not run pip at all: it says why, and says what would work.
``PyReconstruct.modules.constants.frozen`` already records the same fact --
``script_launch_prefix``'s docstring says the frozen exe has no Python CLI --
and the frozen branch is detected with that module's canonical ``is_frozen``,
which the ``PYRECON_FORCE_FROZEN=1`` environment variable below drives.

Three properties are pinned here, one per failure mode:

1. The command targets the running interpreter (``sys.executable -m pip``),
   with no shell.
2. A ``returncode == 0`` whose import still fails is reported, not raised.
3. A non-zero return code never imports the module, whichever explanation it
   goes on to give.

That last one used to read "the pip-absent path keeps its existing behavior
exactly", and it asserted the one message the ``else`` branch had at the time.
That is no longer a single message: ``install_module`` now asks
``pip_is_reachable()`` first and sends a genuinely pip-less environment to
``no_pip_message`` instead of to the generic "try pip installing it in a
terminal" notice (see ``test_install_module_without_pip.py``, which owns the
text of both). Which branch that is depends on the machine, and neither test
below said which one it wanted -- so both read the ambient environment and
asserted the generic text. They passed on any machine with a ``pip`` on
``PATH``, including every CI runner, and failed in this project's own
documented ``uv sync`` environment, which has no pip in it at all. The two
tests below now pin the branch they mean, one each, and neither can be decided
by the environment the suite happens to run in.
"""

import sys

import pytest

from PyReconstruct.modules.backend.imports import mod_imports


@pytest.fixture
def captured(monkeypatch):
    """Route both dialogs into a dict instead of onto a screen."""

    seen = {"notes": [], "confirms": []}

    monkeypatch.setattr(mod_imports, "note", lambda msg: seen["notes"].append(msg))

    def fake_confirm(msg, *a, **k):
        seen["confirms"].append(msg)
        return True  # accept the install; these tests are about what follows

    monkeypatch.setattr(mod_imports, "notifyConfirm", fake_confirm)

    return seen


def _recording_pip(monkeypatch, returncode=0):
    """Record every ``subprocess.run`` call and return a canned result.

    Returns the list the calls land in, as ``(args, kwargs)`` pairs.
    """

    calls = []

    class _Completed:
        stdout = ""
        stderr = ""

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        result = _Completed()
        result.returncode = returncode
        return result

    monkeypatch.setattr(mod_imports.subprocess, "run", fake_run)

    return calls


def _unimportable(monkeypatch, name):
    """Make every ``__import__(name)`` raise ``ModuleNotFoundError``.

    This is what a mismatched-interpreter install looks like from inside the
    running process: pip said it worked, and the module is still not here. A
    ``sys.modules`` entry cannot express "raises on import", so the failure is
    injected as a meta path finder whose loader raises.
    """

    exc = ModuleNotFoundError(f"No module named '{name}'")

    class _Loader:
        @staticmethod
        def create_module(spec):
            raise exc

        @staticmethod
        def exec_module(module):  # pragma: no cover - create_module raises first
            raise exc

    class _Finder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if fullname != name:
                return None
            from importlib.machinery import ModuleSpec

            return ModuleSpec(fullname, _Loader())

    monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Finder()] + list(sys.meta_path))


def _pip_present(monkeypatch):
    """A pip exists on ``PATH``, so a failed install has some other cause.

    Only ``shutil.which`` is patched: ``pip_is_reachable`` answers True if
    *either* route finds one, so an environment whose ``find_spec("pip")``
    already succeeds gives the same answer either way.
    """

    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: "/usr/bin/pip")


def _pip_absent(monkeypatch):
    """Neither route to a pip exists: not importable, not on ``PATH``."""

    monkeypatch.setattr(mod_imports.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(mod_imports.shutil, "which", lambda name: None)


def _never_call_subprocess(monkeypatch):
    """Fail loudly if anything shells out. Returns nothing to inspect."""

    def boom(*args, **kwargs):
        raise AssertionError(f"subprocess.run was called: {args!r} {kwargs!r}")

    monkeypatch.setattr(mod_imports.subprocess, "run", boom)


## ---------------------------------------------------------------- the command


def test_pip_install_targets_the_running_interpreter(monkeypatch, captured):
    """The whole point: install where the import will look.

    ``pip install X`` and ``__import__("X")`` have to agree on which Python
    they mean. A bare ``pip`` off ``PATH`` carries no such guarantee.
    """

    calls = _recording_pip(monkeypatch)
    monkeypatch.setattr(mod_imports, "module_path", lambda module: "/somewhere")

    assert mod_imports.install_module("svgwrite") is True

    assert len(calls) == 1
    args, kwargs = calls[0]
    command = args[0]

    assert command == [sys.executable, "-m", "pip", "install", "svgwrite"], (
        "the install must name the running interpreter explicitly; a bare "
        f"`pip` can belong to another one. Got: {command!r}"
    )

    ## The original defect in its most literal form, so a revert cannot pass.
    assert not isinstance(command, str), (
        "a string command means `shell=True` and a bare `pip` again"
    )
    assert kwargs.get("shell") is not True


def test_the_pip_name_is_used_and_the_import_name_is_not(monkeypatch, captured):
    """Packages whose distribution name differs from their import name.

    ``cloudvolume`` is imported under that name and installed as
    ``cloud-volume``; ``dask`` is pinned. Both go on the command line as one
    argument each, with no shell to re-split them.
    """

    calls = _recording_pip(monkeypatch)
    monkeypatch.setattr(mod_imports, "module_path", lambda module: "/somewhere")

    assert mod_imports.install_module(("cloudvolume", "cloud-volume")) is True

    command = calls[0][0][0]
    assert command == [sys.executable, "-m", "pip", "install", "cloud-volume"]

    calls.clear()

    assert mod_imports.install_module(("dask", "dask==2024.12.1")) is True

    command = calls[0][0][0]
    assert command[-1] == "dask==2024.12.1", (
        "the version pin must survive as a single argument"
    )


## ------------------------------------------- returncode 0, import still fails


def test_successful_pip_whose_import_fails_is_reported_not_raised(
    monkeypatch, captured
):
    """The crash itself: pip says yes, the interpreter says no.

    This is the mismatched-interpreter install. ``install_module`` sees
    ``returncode == 0`` and calls ``module_path``, whose ``__import__`` raises
    ``ModuleNotFoundError``. Before the guard this test does not fail an
    assertion, it *errors* with that exception -- which is precisely the point:
    the exception escaped the function, and with ``console=False`` the user saw
    nothing usable.
    """

    _recording_pip(monkeypatch, returncode=0)
    _unimportable(monkeypatch, "svgwrite")

    assert mod_imports.install_module("svgwrite") is False, (
        "an install the running interpreter cannot import is not a success; "
        "reporting True sends the caller on to import it and crash"
    )

    assert len(captured["notes"]) == 1
    message = captured["notes"][0]

    assert "svgwrite" in message
    assert "still cannot import it" in message
    assert "No module named 'svgwrite'" in message
    ## Actionable: the exact command that targets the right interpreter.
    assert f"{sys.executable} -m pip install svgwrite" in message
    assert "successfully installed" not in message


def test_the_caller_is_told_the_feature_is_unusable(monkeypatch, captured):
    """End to end: ``modules_available`` must not return True off that install.

    Catching the exception is not sufficient on its own. Nothing went into the
    ``unloadable`` bucket on this path, so if ``install_module`` returned True
    the caller would take the feature as available and import the module
    itself -- moving the same crash one frame out.
    """

    _recording_pip(monkeypatch, returncode=0)
    _unimportable(monkeypatch, "svgwrite")

    assert mod_imports.modules_available("svgwrite", notify=True) is False

    ## One offer, one explanation. Re-prompting after a "successful" install
    ## would just repeat it.
    assert len(captured["confirms"]) == 1
    assert len(captured["notes"]) == 1


## ------------------------------------------- a failed install, either branch


def test_pip_absent_explains_the_absence_and_never_imports(monkeypatch, captured):
    """No pip anywhere: the module is not imported, and the notice says why.

    A missing ``pip`` exits 127 through a shell and 1 through
    ``sys.executable -m pip``; either way the ``else`` branch runs and
    ``module_path`` is never reached, so this failure cannot arrive at the
    ``returncode == 0`` guard above.

    On the message, only what both halves of ``no_pip_message`` say: the
    install failed for want of a pip, rather than the generic "try pip
    installing it in a terminal", which names the command just established not
    to exist. Which half runs turns on ``uv_created_environment``, and the text
    of each is pinned in ``test_install_module_without_pip.py`` -- asserting it
    again here would only duplicate that, and duplicating it is what left these
    two tests reading the ambient environment in the first place.
    """

    _recording_pip(monkeypatch, returncode=127)
    _pip_absent(monkeypatch)

    def must_not_import(module):
        raise AssertionError("module_path was called on a failed install")

    monkeypatch.setattr(mod_imports, "module_path", must_not_import)

    assert mod_imports.install_module("svgwrite") is False

    assert len(captured["notes"]) == 1
    message = captured["notes"][0]

    assert message.startswith("svgwrite could not be installed:")
    assert "there was no pip command to run." in message
    assert "Then restart PyReconstruct." in message

    ## The generic advice is wrong here and must not be what gets shown.
    assert "Something went wrong" not in message


def test_a_reachable_pip_that_failed_keeps_the_generic_advice(monkeypatch, captured):
    """Pip ran and pip failed: retrying it in a terminal is real advice.

    The other side of the discrimination, and the reason the branch is chosen
    by probing for a pip rather than by reading the return code: a ``1`` from a
    package that is not on the index looks nothing like a missing pip, and
    telling that user their environment has no pip would be a new wrong message
    for an old one. ``module_path`` is not reached on this path either.
    """

    _recording_pip(monkeypatch, returncode=1)
    _pip_present(monkeypatch)
    monkeypatch.setattr(
        mod_imports,
        "module_path",
        lambda module: pytest.fail("module_path was called on a failed install"),
    )

    assert mod_imports.install_module("svgwrite") is False

    assert len(captured["notes"]) == 1
    assert captured["notes"][0] == (
        "Something went wrong. "
        "Please try pip installing svgwrite in a terminal."
    )


## ------------------------------------------------------------- the frozen build


def test_a_frozen_bundle_does_not_shell_out_at_all(monkeypatch, captured):
    """``sys.executable -m pip`` is not a fix here; it relaunches the app.

    Verified against a PyInstaller one-folder build: the bootloader hands
    ``-m pip install X`` to the application as ``sys.argv`` rather than acting
    on it, so the "install" is a second copy of the app. With
    ``capture_output=True`` the first copy blocks until that one is closed, and
    the exit code it finally reads is ``0``. Applying the source-install fix
    blindly would therefore have replaced a conditional crash with a guaranteed
    hang and a false success. A frozen bundle runs no pip command.
    """

    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")
    _never_call_subprocess(monkeypatch)

    assert mod_imports.install_module("svgwrite") is False

    assert len(captured["notes"]) == 1
    message = captured["notes"][0]

    assert "svgwrite" in message
    assert "self-contained application bundle" in message
    assert "run PyReconstruct from source" in message
    assert "successfully installed" not in message


def test_a_frozen_bundle_is_not_offered_the_install_prompt(monkeypatch, captured):
    """Do not ask a question whose only true answer is "that cannot work".

    The same reasoning the file already applies to a missing *native* library:
    an offer that cannot be honoured is worse than a plain explanation.
    """

    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")
    _never_call_subprocess(monkeypatch)
    _unimportable(monkeypatch, "svgwrite")

    assert mod_imports.modules_available("svgwrite", notify=True) is False

    assert captured["confirms"] == [], (
        "a frozen bundle was offered a pip install it cannot perform"
    )
    assert len(captured["notes"]) == 1
    assert "self-contained application bundle" in captured["notes"][0]


def test_a_source_install_is_still_offered_the_prompt(monkeypatch, captured):
    """The other side of the frozen guard: nothing changes off a bundle.

    Without this, deleting the ``is_frozen()`` condition and always refusing
    would still pass every test above.
    """

    monkeypatch.delenv("PYRECON_FORCE_FROZEN", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    _recording_pip(monkeypatch, returncode=0)
    _unimportable(monkeypatch, "svgwrite")

    assert mod_imports.modules_available("svgwrite", notify=True) is False

    assert len(captured["confirms"]) == 1
    assert "install them into your current environment" in captured["confirms"][0]

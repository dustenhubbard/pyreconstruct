"""Regression test for ``modules_available`` crashing on a native-library failure.

``modules_available`` probes each module with ``__import__`` inside a ``try``
that caught ``ModuleNotFoundError`` only. That is the wrong exception for a
module which is a wrapper around a native library: ``import cairosvg`` runs
``cairocffi``'s ``dlopen`` at import time and raises ``OSError:
no library called "cairo-2" was found`` on a machine with the wheel installed
and no system Cairo. The ``OSError`` escaped the guard, out of
``MainWindow.exportSectionPNG`` (``main_window.py``, ``File > Export > PNG``)
and into ``customExcepthook`` as a crash report.

Declaring ``cairosvg`` is what made that reachable: the ``launch/*`` scripts run
``pip install -r requirements.txt`` on every startup, so every user now has the
Python package, while nothing ships native Cairo on macOS or Windows. Before the
declaration the same machine had no ``cairosvg`` at all, got ``ModuleNotFoundError``,
and saw the handled install prompt.

The remedies are different in kind, so the message has to be too: a missing
*package* is fixed by the pip install ``modules_available`` offers, a missing
*native library* is not, and offering the install for it sends the user down a
path that cannot work.

There are *two* imports on the way to the same crash, not one. The probe is the
first. The second is ``install_module``: when the package really is absent the
user is offered the pip install, and on success ``install_module`` calls
``module_path``, whose own unguarded ``__import__`` raises the same ``OSError``
for the same reason. That one is pre-existing rather than introduced by
declaring ``cairosvg`` -- and declaring it makes the path *rarer*, since the
package is now installed at startup and the probe lands in the handled bucket
-- but it ends in ``customExcepthook`` all the same, so it is guarded and
tested here too. Note that catching it is not sufficient on its own: on that
path nothing went into the ``unloadable`` bucket, so ``modules_available``
would return ``True`` off the back of a successful ``pip install`` and the
caller would import the module and crash. ``install_module`` has to report the
install as failed, which is what the tests below pin.

CI installs ``libcairo2``, so the real ``cairosvg`` import succeeds there and
cannot exercise this branch. These tests inject the failure with a stub module
instead, which also keeps them platform-independent.
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
        return False  # decline the install; the accept path shells out to pip

    monkeypatch.setattr(mod_imports, "notifyConfirm", fake_confirm)
    return seen


def _install_stub(monkeypatch, name, exc):
    """Make ``__import__(name)`` raise ``exc``.

    A real ``sys.modules`` entry cannot express "raises on import", so this
    patches the finder the only way that works from a test: a meta path hook
    whose loader raises. ``modules_available`` calls the builtin ``__import__``,
    so the exception has to come out of the import machinery itself rather than
    out of a monkeypatched name.
    """

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


def _install_staged_stub(monkeypatch, name, exceptions):
    """Make the first ``len(exceptions)`` imports of ``name`` raise, in order.

    Models "the package was genuinely absent, pip supplied it, and the native
    library it wraps is still not there": the probe sees
    ``ModuleNotFoundError``, the post-install verification sees ``OSError``.
    Once the list is exhausted the finder steps aside and the real import
    machinery runs, so a staged ``[ModuleNotFoundError]`` leaves a genuinely
    importable module behind.
    """

    staged = list(exceptions)

    class _Loader:
        @staticmethod
        def create_module(spec):
            raise staged.pop(0)

        @staticmethod
        def exec_module(module):  # pragma: no cover - create_module raises first
            raise staged.pop(0)

    class _Finder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if fullname != name or not staged:
                return None
            from importlib.machinery import ModuleSpec

            return ModuleSpec(fullname, _Loader())

    monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Finder()] + list(sys.meta_path))


def _fake_pip(monkeypatch, returncode=0):
    """Let the accept-the-install path run without shelling out to pip."""

    class _Completed:
        pass

    _Completed.returncode = returncode
    _Completed.stdout = _Completed.stderr = ""

    monkeypatch.setattr(
        mod_imports.subprocess, "run", lambda *a, **k: _Completed()
    )


def _accept_the_prompt(monkeypatch, captured):
    """Answer yes to the install prompt (the fixture's default is no)."""

    def yes(msg, *a, **k):
        captured["confirms"].append(msg)
        return True

    monkeypatch.setattr(mod_imports, "notifyConfirm", yes)


def test_accepted_install_then_unloadable_library_does_not_propagate(
    monkeypatch, captured
):
    """The second door into the same crash: accept the install, then verify.

    ``modules_available``'s probe is only one of two places that import the
    module. When the package really is absent the user is offered the pip
    install, and on success ``install_module`` imports the module again --
    via ``module_path`` -- to report where it landed. For a native wrapper on
    a machine with no system library that second import raises the same
    ``OSError`` the probe now catches, and it used to escape
    ``modules_available`` into ``customExcepthook``, exactly as the probe's
    did.

    Without the guard in ``install_module`` this test does not fail an
    assertion -- it errors with the ``OSError``.
    """
    _install_staged_stub(
        monkeypatch,
        "cairosvg",
        [
            ModuleNotFoundError("No module named 'cairosvg'"),
            OSError('no library called "cairo-2" was found'),
        ],
    )
    _fake_pip(monkeypatch)
    _accept_the_prompt(monkeypatch, captured)

    assert mod_imports.modules_available("cairosvg", notify=True) is False, (
        "a pip install that cannot make the feature usable was reported as "
        "success; the caller would go on to import cairosvg and crash"
    )

    ## Exactly one prompt: the original offer, which was correct at the time
    ## (the package really was missing). Offering it again after the install
    ## already succeeded would be a dead end.
    assert len(captured["confirms"]) == 1
    assert len(captured["notes"]) == 1
    message = captured["notes"][0]
    assert 'no library called "cairo-2" was found' in message
    assert "libcairo2" in message
    assert "brew install cairo" in message
    assert "reinstalling it will not help" in message
    assert "successfully installed" not in message
    assert "install them into your current environment" not in message


def test_accepted_install_of_a_loadable_module_still_returns_true(
    monkeypatch, captured
):
    """The ordinary success path is untouched by the new guard.

    Same sequence, but the module imports cleanly after the install, so
    ``install_module`` still reports where it landed and ``modules_available``
    still returns ``True``.
    """
    _install_staged_stub(
        monkeypatch, "json", [ModuleNotFoundError("No module named 'json'")]
    )
    _fake_pip(monkeypatch)
    _accept_the_prompt(monkeypatch, captured)

    assert mod_imports.modules_available("json", notify=True) is True

    assert len(captured["confirms"]) == 1
    assert len(captured["notes"]) == 1
    assert "successfully installed to" in captured["notes"][0]


def test_native_library_oserror_does_not_propagate(monkeypatch, captured):
    """The whole point: an OSError from the probe is reported, not raised.

    Without the widened ``except`` this test does not fail an assertion -- it
    errors with the OSError, exactly as ``exportSectionPNG`` did.
    """
    _install_stub(monkeypatch, "cairosvg", OSError('no library called "cairo-2" was found'))

    assert mod_imports.modules_available(["svgwrite", "cairosvg"], notify=False) is False


def test_native_library_message_names_the_real_remedy(monkeypatch, captured):
    """The OSError path must name the system library, and must not offer pip."""
    _install_stub(monkeypatch, "cairosvg", OSError('no library called "cairo-2" was found'))

    assert mod_imports.modules_available("cairosvg", notify=True) is False

    assert not captured["confirms"], (
        "a pip install was offered for a missing *native* library, which "
        "reinstalling the Python package cannot fix"
    )
    assert len(captured["notes"]) == 1
    message = captured["notes"][0]
    assert "libcairo2" in message
    assert "brew install cairo" in message
    assert "libcairo-2.dll" in message
    assert 'no library called "cairo-2" was found' in message
    # The pip prompt's wording must not leak into this branch.
    assert "install them into your current environment" not in message


def test_missing_package_still_offers_the_pip_install(monkeypatch, captured):
    """The ModuleNotFoundError path is untouched: that remedy does work."""
    _install_stub(
        monkeypatch, "svgwrite", ModuleNotFoundError("No module named 'svgwrite'")
    )

    assert mod_imports.modules_available("svgwrite", notify=True) is False

    assert not captured["notes"], "the native-library notice fired for a missing package"
    assert len(captured["confirms"]) == 1
    assert "svgwrite" in captured["confirms"][0]
    assert "install them into your current environment" in captured["confirms"][0]


def test_both_failures_get_their_own_message(monkeypatch, captured):
    """A mixed batch reports each failure with the remedy that fits it."""
    _install_stub(
        monkeypatch, "svgwrite", ModuleNotFoundError("No module named 'svgwrite'")
    )
    _install_stub(monkeypatch, "cairosvg", OSError('no library called "cairo-2" was found'))

    assert mod_imports.modules_available(["svgwrite", "cairosvg"], notify=True) is False

    assert len(captured["notes"]) == 1
    assert len(captured["confirms"]) == 1
    # The pip prompt lists only what pip can actually install.
    assert "cairosvg" not in captured["confirms"][0]
    assert "svgwrite" in captured["confirms"][0]


def test_importable_modules_still_return_true(captured):
    """The happy path is unchanged -- no dialog, True."""
    assert mod_imports.modules_available(["json", "pathlib"], notify=True) is True
    assert not captured["notes"] and not captured["confirms"]

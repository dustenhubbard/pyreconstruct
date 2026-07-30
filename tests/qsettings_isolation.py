"""Point the whole suite's `QSettings` at a throwaway location, and guard the
real one.

Why this module exists. Running the suite used to edit the developer's own
application preferences, through three separate routes in one night:

1. A fixture called `QSettings.clear()` and rewrote `allKeys()`. On macOS
   `NativeFormat` is `NSUserDefaults`, and `allKeys()` on an app domain also
   returns the *global* domain, so the rewrite copied 67 system defaults
   (`Apple*`, `com/apple/trackpad/*`) into the app's own plist.
2. A test assigned `series.user`. That setter is `setOption("username", value)`,
   which writes the machine-wide scope, and it overwrote the stored username.
3. `MainWindow.openSeries` calls `addToRecentSeries`, so every `main_window`
   fixture build prepended a pytest `tmp_path` to `recently_opened_series`, and
   left `last_folder` pointing at a directory that no longer exists.

Snapshot-and-restore fixtures fix the routes they enumerate and nothing else.
This is a redirect instead: it applies to the whole session, no test opts in,
and a route added tomorrow is covered without anyone remembering it exists.

## The two obvious mechanisms do not work on macOS. Measured, not assumed.

With `PySide6==6.5.2` on macOS 27, for `QSettings("KHLab", "PyReconstruct")`:

- `QStandardPaths.setTestModeEnabled(True)` moves `AppConfigLocation` to
  `~/.qttest/Library/Preferences`, and `QSettings` ignores it completely:
  `fileName()` still returns `~/Library/Preferences/com.khlab.PyReconstruct.plist`.
  `NativeFormat` goes through `CFPreferences`, which does not consult
  `QStandardPaths`.
- `QSettings.setDefaultFormat(IniFormat)` plus
  `QSettings.setPath(IniFormat, UserScope, tmp)` does change `defaultFormat()`,
  and the two-argument organization/application constructor still comes back
  `NativeFormat` with the same real path. `setPath` is documented as having no
  effect on `NativeFormat`, and on this platform that constructor stays native.

What does work, measured the same way: the four-argument
`QSettings(IniFormat, UserScope, org, app)` constructor honors `setPath`, giving
`<tmp>/KHLab/PyReconstruct.ini` with `format()` reporting `IniFormat`. So the
redirect is a `QSettings` subclass that rewrites any construction into that
form, installed over the name `QSettings` itself.

## Where the substitution is installed

`PySide6.QtCore.QSettings` is rebound, which covers every deferred import
(`QSettingsStore._settings` imports inside the method) and every module imported
after this one. Modules that already bound the name at import time are swept out
of `sys.modules` and rebound individually, which is what catches
`gui/main/main_window.py`: it gets `QSettings` through
`from .main_imports import *`, so the name lives in its namespace, not in
`main_imports`' alone.

Installation happens at *import* time rather than in a fixture. A fixture runs
after collection, and collection imports every test module; import-time keeps
the window closed. `tests/conftest.py` imports this module immediately after it
defaults `QT_QPA_PLATFORM`, for the same ordering reason that line has.

## The guard, and why it takes two signals rather than one

Redirecting is only half of it. Incident four will arrive by a route this
module does not anticipate: a test that reaches the real class through a
reference it captured earlier, a `monkeypatch` teardown that restores the real
name, a subprocess. So the real store is watched as well as avoided.

The first signal is `RealSettingsGuard`, which fingerprints the real settings
files on disk at session start and re-checks at session end. It watches the
whole domain family, not one file, so a new per-series domain
(`PyReconstruct-<code>`) is caught too.

A file digest cannot say *who* wrote the file, and on this platform nothing can
recover that from the file: `NativeFormat` writes go through `cfprefsd`, so
neither the suite nor the application writes those bytes itself, and both land
in the same file at the same mtime with the same key names. The developer
normally has the application open while running the suite, and the application
saves its own window state and recent-series list as it goes. A digest change
is therefore *expected* during an ordinary run and says nothing about the suite.

So the second signal is the one that can be attributed: `_install_tripwire`
wraps the mutating methods on the real `QSettings` class and records any call
made on an instance that is not the isolated subclass and does address a file
outside the isolation root. That is direct, in-process evidence that this
session wrote the real store, it names the test that did it, and it does not
depend on `cfprefsd` having flushed by the time the session ends.

The two combine as follows:

- a recorded mutation, digest changed or not: **fail**, and name the test.
- digest changed, nothing recorded: **warn**, and say that the suite is not the
  writer and what the likely causes are. Set `PYRECON_TEST_STRICT_SETTINGS=1` to
  make this a failure too, which is what a CI machine wants, since nothing else
  should be touching the store there.
- neither: silent.

A run that fails on something the developer cannot control, in his normal
working configuration, teaches him to ignore the one message that matters.
"""

import atexit
import contextlib
import hashlib
import os
import plistlib
import shutil
import sys
import tempfile
import time
import traceback
import warnings

import pytest

# The real domain this whole module exists to protect. Both scopes that
# `QSettingsStore` addresses live under it: the global one is exactly `APP`, and
# a per-series one is `f"{APP}-{code}"`.
ORG = "KHLab"
APP = "PyReconstruct"

#: Set this to make an unattributed change to the real store fail the session
#: instead of warning. For CI, where the developer's application is not running
#: and any change to the store really is the suite's fault.
STRICT_ENV = "PYRECON_TEST_STRICT_SETTINGS"

# Populated by `_install()`; None means Qt was not importable and there is
# nothing to isolate (see the ImportError branch).
isolation_root = None
guard = None

_real_qsettings = None
_isolated_qsettings = None
_rebound_modules = ()


# --- fingerprinting the real store -------------------------------------------


def _digest(path):
    """sha256 of a file's bytes, or None if it does not exist."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def _keys(path):
    """Best-effort key set of a settings file, for a useful failure message.

    Only used to describe a change that has already been detected by digest, so
    an unparseable file is not an error: the digest is the assertion, this is
    the explanation. `plistlib` covers macOS `NativeFormat`; the `.conf`/`.ini`
    backends are parsed loosely enough that a section header does not matter.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return set()
    try:
        parsed = plistlib.loads(raw)
    except Exception:
        pass
    else:
        return set(parsed) if isinstance(parsed, dict) else set()
    found = set()
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#", "[")) or "=" not in line:
            continue
        found.add(line.split("=", 1)[0].strip())
    return found


class RealSettingsGuard:
    """Describe what changed in the real settings files during the session.

    Detection only. What a change *means* is decided by `session_report`, which
    weighs this against the tripwire, because a digest cannot say who wrote the
    file and on macOS the application usually did.

    Watches a directory for every file whose name starts with `prefix`, which
    is the whole domain family rather than a single file: on macOS that is
    `com.khlab.PyReconstruct.plist` plus every `...-<series code>.plist`. A file
    appearing is as much a failure as a file changing, because a per-series
    domain is created on first write and the suite opens series it invented.

    Deliberately not `QSettings`-based. Reading the real store through the real
    class to check on it would reintroduce exactly the reference this module is
    trying to keep out of the suite, and a file digest is a stronger claim than
    an enumerated key list anyway: it catches a key nobody thought to list.

        Params:
            directory (str): where the real settings files live.
            prefix (str): the filename prefix identifying the domain family.
    """

    def __init__(self, directory, prefix):
        self.directory = directory
        self.prefix = prefix
        self.baseline = None
        # captured alongside the baseline digests, while the baseline bytes are
        # still the bytes on disk, so a failure can name the offending keys
        self.baseline_keys = {}

    def _matches(self):
        """Absolute paths of every watched file currently on disk."""
        try:
            names = os.listdir(self.directory)
        except OSError:
            return []
        # macOS treats the domain case-insensitively (`com.KHLab.PyReconstruct`
        # and `com.khlab.PyReconstruct` are one store), so match that way.
        low = self.prefix.lower()
        return sorted(
            os.path.join(self.directory, name)
            for name in names
            if name.lower().startswith(low)
        )

    def fingerprint(self):
        """A {path: sha256} map of the watched files."""
        return {path: _digest(path) for path in self._matches()}

    def snapshot(self):
        """Record the current fingerprint and key sets as the baseline."""
        self.baseline = self.fingerprint()
        self.baseline_keys = {path: _keys(path) for path in self._matches()}
        return self.baseline

    def diff(self):
        """Human-readable descriptions of every change since `snapshot()`.

        Empty list means the real store is untouched.
        """
        if self.baseline is None:  # pragma: no cover - guarded by the caller
            raise RuntimeError("snapshot() must be called before diff()")
        now = self.fingerprint()
        problems = []
        for path in sorted(set(self.baseline) | set(now)):
            before = self.baseline.get(path)
            after = now.get(path)
            if before == after:
                continue
            if before is None:
                problems.append(
                    f"created: {path} (keys: {sorted(_keys(path)) or 'none'})"
                )
            elif after is None:
                problems.append(f"deleted: {path}")
            else:
                was = self.baseline_keys.get(path, set())
                now_keys = _keys(path)
                detail = []
                if now_keys - was:
                    detail.append(f"keys added: {sorted(now_keys - was)}")
                if was - now_keys:
                    detail.append(f"keys removed: {sorted(was - now_keys)}")
                if not detail:
                    detail.append("same key set, changed values")
                problems.append(f"modified: {path} ({'; '.join(detail)})")
        return problems


# --- attributing a write to this process --------------------------------------

#: The `QSettings` methods that can change stored values. Reads are harmless --
#: a test that only reads the real store is a bug worth fixing but not
#: pollution -- so the tripwire ignores them and stays cheap.
_MUTATORS = ("setValue", "remove", "clear")

#: Every mutation of the real store recorded during this session.
_bypasses = []


class RealSettingsChanged(UserWarning):
    """The real settings changed and the suite is demonstrably not the writer."""


class Bypass:
    """One recorded mutation of the real store through the real `QSettings`.

        Params:
            method (str): the `QSettings` method called.
            key (str): the settings key, when the call named one.
            path (str): the settings file the instance addresses.
            test (str): the test that was running, from `PYTEST_CURRENT_TEST`.
            stack (str): the innermost frames of the call, to find the culprit.
    """

    def __init__(self, method, key, path, test, stack):
        self.method = method
        self.key = key
        self.path = path
        self.test = test
        self.stack = stack

    def describe(self):
        """A block naming the call, the file, the test, and the call site."""
        key = "" if self.key is None else f"({self.key!r})"
        head = f"{self.method}{key} -> {self.path}"
        where = self.test or "no test (import or session-level code)"
        return f"{head}\n      during: {where}\n{self.stack}"


def recorded_bypasses():
    """Every mutation of the real store recorded so far this session."""
    return tuple(_bypasses)


@contextlib.contextmanager
def deliberate_bypass():
    """Discard the tripwire records made inside the block.

    The tests that prove the tripwire fires have to trip it, and a proof that
    left a record behind would fail the session it was proving. Yields a list,
    filled in on exit with what was recorded and removed, so a test can assert
    against it after the block.
    """
    start = len(_bypasses)
    recorded = []
    try:
        yield recorded
    finally:
        recorded.extend(_bypasses[start:])
        del _bypasses[start:]


def _install_tripwire(real, isolated, root):
    """Record mutations that reach the real class and land outside `root`.

    Wraps the mutating methods on the *real* class, which is the one a bypass
    holds. Two conditions have to hold before a call is recorded, and both
    matter:

    - the instance is not an `isolated` one. The isolated subclass inherits
      these methods, so every ordinary settings write in the suite arrives here
      too, and is not a bypass.
    - the file it addresses is outside the isolation root. A bypass that still
      resolves into the root writes nothing real, because `_install` also
      redirects the real class's `IniFormat` path. Only a call that would touch
      a file outside the root is pollution.

    This is the only evidence available that *this process* wrote the real
    store, and unlike the digest it does not need `cfprefsd` to have flushed.
    """
    absolute_root = os.path.abspath(root)

    def call_site():
        """The innermost frames that belong to this repository, as text.

        The raw stack at a settings write is mostly pluggy and `_pytest`
        plumbing, which tells the reader nothing about which line to change, so
        framework frames are dropped and the last few of what remains are kept.
        """
        frames = [
            frame
            for frame in traceback.extract_stack()[:-2]
            if "/site-packages/" not in frame.filename
            and "/_pytest/" not in frame.filename
            and not frame.filename.startswith("<")
            and frame.filename != __file__
        ]
        return "".join(traceback.format_list(frames[-3:]))

    def target_outside_root(instance):
        """The addressed file, or None when it is inside the isolation root."""
        try:
            path = instance.fileName()
        except Exception:  # pragma: no cover - defensive, a deleted C++ object
            return None
        if not path:
            return None
        if os.path.abspath(path).startswith(absolute_root):
            return None
        return path

    def wrap(name):
        original = getattr(real, name)

        def tripwire(self, *args, **kwargs):
            if not isinstance(self, isolated):
                path = target_outside_root(self)
                if path is not None:
                    named = args[0] if args and isinstance(args[0], str) else None
                    _bypasses.append(
                        Bypass(
                            method=name,
                            key=named,
                            path=path,
                            test=os.environ.get("PYTEST_CURRENT_TEST"),
                            stack=call_site(),
                        )
                    )
            return original(self, *args, **kwargs)

        tripwire.__name__ = name
        tripwire.__qualname__ = f"{real.__name__}.{name}"
        setattr(real, name, tripwire)

    for name in _MUTATORS:
        wrap(name)


# --- what the end of the session says -----------------------------------------


def _when(path):
    """Local mtime of a path, for correlating a change with something else."""
    try:
        return time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))
        )
    except OSError:
        return "no longer present"


def strict_requested():
    """Whether an unattributed change should fail rather than warn."""
    value = os.environ.get(STRICT_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no")


def session_report(problems, bypasses, root=None, strict=False):
    """Decide what the end of the session should report.

        Params:
            problems (list): `RealSettingsGuard.diff()` output.
            bypasses (tuple): `recorded_bypasses()` output.
            root (str): the isolation root, quoted in the failure message.
            strict (bool): treat an unattributed change as a failure.

        Returns:
            tuple: `(level, message)`, where level is "ok", "warn" or "fail".
              The message is empty when the level is "ok".
    """
    if bypasses:
        detail = "\n".join(f"  - {b.describe()}" for b in bypasses)
        message = (
            "this test session wrote the real application settings.\n\n"
            "Attributed, not inferred: the suite called a mutating QSettings "
            "method on an\ninstance addressing a file outside the isolation "
            "root.\n\n" + detail + "\n"
            "Every settings route in the suite is supposed to be redirected to\n"
            f"  {root}\n"
            "so the code above is holding a reference to the real QSettings "
            "class that it\ncaptured before tests/qsettings_isolation.py was "
            "imported. Look it up on\nPySide6.QtCore at call time instead of "
            "binding it at import time."
        )
        if problems:
            changed = "\n".join(f"  - {p}" for p in problems)
            message += (
                "\n\nThe watched files also changed on disk, consistent with "
                "the above:\n" + changed
            )
        return "fail", message

    if not problems:
        return "ok", ""

    changed = "\n".join(
        f"  - {p}\n    last written: {_when(_path_of(p))}" for p in problems
    )
    message = (
        "the real application settings changed while this session was running,\n"
        "and the suite is not the writer.\n\n" + changed + "\n\n"
        "The suite records every mutating QSettings call that reaches the real\n"
        "store, and it recorded none, so these bytes came from another process.\n"
        "On macOS the native backend writes through cfprefsd rather than from\n"
        "the writing process, so the file cannot name who changed it. In order of\n"
        "likelihood:\n\n"
        "  - the application is open and saved its own preferences, such as "
        "window\n    state or the recently opened series list. That is normal "
        "and needs no\n    action. Check with: pgrep -fl PyReconstruct\n"
        "  - a second checkout is running this suite without this redirect.\n"
        "  - a subprocess of this run that does not load tests/conftest.py.\n\n"
        "Nothing in this run is known to be wrong. This is a notification, not a\n"
        f"failure. Set {STRICT_ENV}=1 to make it a failure, which is\n"
        "what a CI machine wants: there, nothing else should be writing."
    )
    if strict:
        return "fail", message + f"\n\nFailing because {STRICT_ENV} is set."
    return "warn", message


def _path_of(problem):
    """Recover the path from a `diff()` line, for its mtime. Best effort."""
    body = problem.split(": ", 1)[-1]
    return body.split(" (", 1)[0].strip()


#: Set when the session ends with something the developer should read, and
#: printed by `pytest_terminal_summary` in conftest.py.
terminal_note = None


# --- the redirect -------------------------------------------------------------


def _build_isolated_class(qsettings, root):
    """Return a `QSettings` subclass that can only address `root`.

    Every construction is rewritten to the four-argument
    `(IniFormat, UserScope, org, app)` form, which is the only one measured to
    honor `setPath` on macOS. The organization and application names are kept as
    the caller passed them, so a per-series scope stays a distinct file and the
    isolated tree mirrors the real one; only the location changes.
    """
    ini = qsettings.Format.IniFormat
    user_scope = qsettings.Scope.UserScope

    class IsolatedQSettings(qsettings):
        """A `QSettings` that cannot reach the real user settings."""

        #: where every instance of this class stores its values
        isolation_root = root

        def __init__(self, *args, **kwargs):
            from PySide6.QtCore import QObject

            parent = kwargs.get("parent") or next(
                (a for a in args if isinstance(a, QObject)), None
            )
            strings = [a for a in args if isinstance(a, str)]
            formats = [a for a in args if isinstance(a, qsettings.Format)]

            if len(formats) == 1 and len(strings) == 1 and args[0] is strings[0]:
                # QSettings(fileName, format): an explicit file, not a domain.
                # Nothing in this repository uses it; redirect the basename into
                # the isolation root rather than trust a path from a test.
                target = os.path.join(root, "explicit", os.path.basename(strings[0]))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                super().__init__(target, ini)
            else:
                organization = strings[0] if strings else ORG
                application = strings[1] if len(strings) > 1 else ""
                super().__init__(ini, user_scope, organization, application)

            if parent is not None:
                self.setParent(parent)

    return IsolatedQSettings


def _rebind(module_names_holding, replacement):
    """Rebind an already-imported `QSettings` name in every module that has one.

    `from PySide6.QtCore import QSettings` copies the class into the importing
    module's namespace, so patching `PySide6.QtCore` alone leaves those bindings
    pointing at the real class. Star imports count: `main_window.py` gets the
    name via `from .main_imports import *`, so it holds its own reference.
    """
    rebound = []
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        try:
            current = getattr(module, "QSettings", None)
        except Exception:  # pragma: no cover - defensive, module __getattr__
            continue
        if current is module_names_holding:
            try:
                setattr(module, "QSettings", replacement)
            except Exception:  # pragma: no cover - immutable module
                continue
            rebound.append(name)
    return tuple(rebound)


def _install():
    """Redirect `QSettings` and arm the guard. Called once, at import time.

    Returns False when Qt is not importable, which is a supported state: with no
    `PySide6` there is no `QSettings` route to isolate, and the Qt-free core
    tests still run.
    """
    global isolation_root, guard, _real_qsettings, _isolated_qsettings
    global _rebound_modules

    try:
        import PySide6.QtCore as qtcore
    except ImportError:
        return False

    _real_qsettings = qtcore.QSettings

    # Resolve the real locations *before* patching, so the guard watches where
    # the app actually stores things on this platform rather than a guess.
    real_file = _real_qsettings(ORG, APP).fileName()
    directory = os.path.dirname(real_file)
    prefix = os.path.splitext(os.path.basename(real_file))[0]
    guard = RealSettingsGuard(directory, prefix)
    guard.snapshot()

    isolation_root = tempfile.mkdtemp(prefix="pyrecon-qsettings-")
    # One directory per session would otherwise accumulate forever, and the
    # session-end guard message quotes the path, so this has to run after it:
    # atexit is later than any pytest hook.
    atexit.register(shutil.rmtree, isolation_root, ignore_errors=True)

    # setPath is what the four-argument IniFormat constructor honors.
    ini = _real_qsettings.Format.IniFormat
    _real_qsettings.setPath(ini, _real_qsettings.Scope.UserScope, isolation_root)
    _real_qsettings.setPath(ini, _real_qsettings.Scope.SystemScope, isolation_root)
    # Not sufficient on macOS (see the module docstring), but it is what makes
    # the plain two-argument constructor land in the isolation root on the
    # platforms where it is honored, so the redirect holds even if the subclass
    # is somehow bypassed.
    _real_qsettings.setDefaultFormat(ini)

    _isolated_qsettings = _build_isolated_class(_real_qsettings, isolation_root)
    # After the subclass exists, because the tripwire has to be able to tell an
    # isolated instance from a bypass, and before the rebind, so a module that
    # kept the real class is instrumented from its first call.
    _install_tripwire(_real_qsettings, _isolated_qsettings, isolation_root)
    _rebound_modules = _rebind(_real_qsettings, _isolated_qsettings)
    qtcore.QSettings = _isolated_qsettings

    # Refuse to run unisolated. A silent failure here is the whole problem this
    # module was written about, so it is an exception at collection time.
    verify_isolated()
    return True


def resolved_path(organization=ORG, application=APP):
    """Where a `QSettings(organization, application)` built now would store."""
    import PySide6.QtCore as qtcore

    return qtcore.QSettings(organization, application).fileName()


def verify_isolated():
    """Raise unless the live `QSettings` name resolves inside the isolation root.

    Checks the global scope and a per-series scope, since they are separate
    files and a partial redirect is worse than none: it looks safe.
    """
    import PySide6.QtCore as qtcore

    if qtcore.QSettings is not _isolated_qsettings:
        raise RuntimeError(
            "PySide6.QtCore.QSettings is not the isolated subclass any more, so "
            "the suite can reach the real user settings. Something rebound it "
            f"(now {qtcore.QSettings!r})."
        )
    for application in (APP, f"{APP}-isolationselfcheck"):
        path = os.path.abspath(resolved_path(ORG, application))
        if not path.startswith(os.path.abspath(isolation_root)):
            raise RuntimeError(
                f"QSettings({ORG!r}, {application!r}) resolves to {path}, which "
                f"is outside the isolation root {isolation_root}. Refusing to "
                "run: the suite would write the real user settings."
            )


# Import-time, deliberately. See the module docstring.
installed = _install()


# --- the session fixture ------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def isolated_qsettings():
    """Assert the isolation held, and report on the real settings.

    Autouse and session-scoped, so it is not something a test opts into. Setup
    re-checks the redirect (a `monkeypatch` of `PySide6.QtCore` in some earlier
    test could have restored the real class on teardown); teardown weighs the
    tripwire against the on-disk digest, which is the half that catches a route
    this module did not predict.

    Only a mutation the suite can be shown to have made is a failure. A digest
    change with nothing recorded is reported and does not fail the run: the
    developer normally has the application open, it writes its own preferences
    while the suite runs, and failing on that would make the check noise. See
    the module docstring.

    Yields the isolation root, for the isolation tests themselves.
    """
    global terminal_note

    if not installed:
        yield None
        return

    verify_isolated()
    yield isolation_root
    verify_isolated()

    level, message = session_report(
        guard.diff(),
        recorded_bypasses(),
        root=isolation_root,
        strict=strict_requested(),
    )
    if level == "ok":
        return
    if level == "warn":
        # Stashed for conftest to print under the pass count, which is where it
        # will be read in a four-thousand-test run. Not stashed for a failure:
        # pytest already prints that in full, and twice is noise.
        terminal_note = message
        warnings.warn(message, RealSettingsChanged, stacklevel=2)
        return
    raise AssertionError(message)

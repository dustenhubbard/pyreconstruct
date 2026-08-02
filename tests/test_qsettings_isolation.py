"""Prove the suite cannot write the real application settings.

Three separate routes reached `QSettings("KHLab", "PyReconstruct")` from the
suite in one night and edited the developer's own preferences. The redirect and
the guard live in `tests/qsettings_isolation.py`; these are the tests that hold
them in place.

Three things are checked that are easy to conflate:

  - *isolation*: every route resolves inside the session's throwaway root, so a
    write cannot land on the real store. One test per known route, plus a sweep
    that fails if any imported module still holds the real class.
  - *detection*: `RealSettingsGuard` actually notices a change. Tested against
    files in `tmp_path` rather than the real store, for the obvious reason, and
    including a genuine `QSettings` write through the real Qt machinery so the
    detection path is the real one and not a hand-written file.
  - *attribution*: a detected change is only the suite's fault if the tripwire
    recorded the suite making it. These are the tests that keep the run from
    failing on a write the developer's own application made, while still failing
    on a write the suite made. They matter because the two are indistinguishable
    on disk, so getting this wrong in either direction is easy: fail always, and
    the check becomes noise to be ignored; fail never, and incident four is
    silent.

The last test is the counterweight: production still resolves to the real
location. An isolation mechanism that also redirected the shipped app would be a
much worse bug than the one it fixes, and it has to be checked from outside the
suite's own process, since inside it the redirect is installed by design.
"""

import os
import plistlib
import subprocess
import sys
import textwrap

import pytest

import qsettings_isolation as qi


pytestmark = pytest.mark.skipif(
    not qi.installed, reason="PySide6 is not installed, so there is nothing to isolate"
)


def _under_root(path):
    return os.path.abspath(path).startswith(os.path.abspath(qi.isolation_root))


def _require_isolated():
    """Hard precondition for any test below that performs a write.

    These tests deliberately exercise the routes that caused the incidents,
    including the `series.user` setter. That is only safe while the redirect
    holds, so every writing test asserts the redirect *first* and fails without
    writing anything if it does not.
    """
    qi.verify_isolated()
    assert _under_root(qi.resolved_path()), qi.resolved_path()


# --- isolation ----------------------------------------------------------------


def test_the_qsettings_name_is_the_isolated_subclass():
    """`PySide6.QtCore.QSettings` is the substitute, not the real class."""
    import PySide6.QtCore as qtcore

    assert qtcore.QSettings is not qi._real_qsettings
    assert issubclass(qtcore.QSettings, qi._real_qsettings)


@pytest.mark.parametrize(
    "application",
    [
        "PyReconstruct",              # the global scope
        "PyReconstruct-someseries",   # a per-series scope
        "PyReconstruct-",             # a series whose code is empty; this file
                                      # exists on disk in the real Preferences
                                      # directory, so the route is real
    ],
)
def test_every_scope_resolves_inside_the_isolation_root(application):
    """Both scopes `QSettingsStore` addresses are redirected, not just the global one.

    A partial redirect is worse than none, because the half that still works
    looks like proof.
    """
    import PySide6.QtCore as qtcore

    settings = qtcore.QSettings("KHLab", application)
    assert settings.format() == qi._real_qsettings.Format.IniFormat
    assert _under_root(settings.fileName()), settings.fileName()


def test_direct_two_argument_construction_writes_into_the_root():
    """The plain `QSettings("KHLab", "PyReconstruct")` form, as written in
    `file_dialog.py`, `whats_new.py`, `main_window.py` and `mouse_palette.py`.
    """
    _require_isolated()
    import PySide6.QtCore as qtcore

    settings = qtcore.QSettings("KHLab", "PyReconstruct")
    settings.setValue("isolation_probe_direct", "landed")
    settings.sync()
    with open(settings.fileName()) as f:
        assert "isolation_probe_direct" in f.read()


def test_the_settings_store_seam_is_isolated():
    """Route with by far the widest reach: `Series.getOption`/`setOption` go
    through `QSettingsStore`, which builds its own `QSettings` from a deferred
    import. 132 `setOption` and 215 `getOption` call sites resolve here.
    """
    _require_isolated()
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    store = QSettingsStore()
    store.set_value(None, "isolation_probe_global", "g")
    store.set_value("probecode", "isolation_probe_series", "s")

    assert _under_root(store._settings(None).fileName())
    assert _under_root(store._settings("probecode").fileName())
    assert store.value(None, "isolation_probe_global", str) == "g"
    assert store.value("probecode", "isolation_probe_series", str) == "s"


def test_the_default_store_helpers_are_isolated():
    """`constants.getdatetime` reads the global "utc" option through
    `default_settings_store()`, and `Series.getOption` falls back on
    `datatypes/series.py`'s `_default_settings_store()`. Both have to be
    isolated, and neither is reached by injecting a store into a `Series`.
    """
    _require_isolated()
    from PyReconstruct.modules.backend.settings_store import default_settings_store
    from PyReconstruct.modules.datatypes.series import _default_settings_store

    for store in (default_settings_store(), _default_settings_store()):
        assert _under_root(store._settings(None).fileName())


def test_overriding_the_default_store_reaches_getOption_too():
    """One `set_default_settings_store()` call closes the whole seam.

    Backlog item: "the undo harness's settings seam only closes one of two
    stores". `datatypes/series.py` used to keep a second module-level cache of
    its own, so `set_default_settings_store()` -- the documented way to redirect
    settings -- reached `constants.getdatetime` and did *not* reach
    `Series.getOption`, which is the route with 215 call sites. The measurement
    harness that hit this closed the sanctioned seam, believed itself isolated,
    and had every `getOption` still resolving the real
    `QSettings("KHLab", "PyReconstruct")` store. It went unnoticed only because
    it passed `log_event=False` everywhere and so never called `addLog` ->
    `series.user` -> `getOption`.

    Asserting on the store object rather than on a completed write, so this test
    states the invariant without performing the write that would prove it the
    unpleasant way. `getOption` writes the default back when a key is absent, so
    a read through a missed seam is a write.
    """
    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore, default_settings_store, set_default_settings_store,
    )
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.datatypes.series import _default_settings_store

    original = default_settings_store()
    injected = DictSettingsStore()

    # No __init__: resolving the store must not need a series on disk, and this
    # keeps the test from reading or writing anything at all.
    series = Series.__new__(Series)
    series.options = {}
    series.code = "seamprobe"

    try:
        set_default_settings_store(injected)
        assert _default_settings_store() is injected
        assert series._settingsStore() is injected, (
            "Series.getOption still resolves a store that "
            "set_default_settings_store() did not close"
        )
    finally:
        set_default_settings_store(original)

    assert _default_settings_store() is original
    assert series._settingsStore() is original


def test_a_series_injected_store_still_wins_over_the_default():
    """Closing the seam must not flatten the two scopes into one.

    `setSettingsStore` is per-series and has to keep taking precedence over the
    process-wide default; `local_series_settings` and a dozen tests depend on
    it. A fix that made `getOption` read the global default unconditionally
    would pass the test above and break every one of those.
    """
    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore, default_settings_store, set_default_settings_store,
    )
    from PyReconstruct.modules.datatypes import Series

    original = default_settings_store()
    process_wide = DictSettingsStore()
    per_series = DictSettingsStore()

    series = Series.__new__(Series)
    series.options = {}
    series.code = "seamprobe"

    try:
        set_default_settings_store(process_wide)
        series.setSettingsStore(per_series)
        assert series._settingsStore() is per_series

        series.setSettingsStore(None)   # documented way back to the default
        assert series._settingsStore() is process_wide
    finally:
        set_default_settings_store(original)


def test_the_series_user_setter_is_isolated():
    """Incident 2, as a regression test.

    `Series.user`'s setter is `setOption("username", value)`, which addresses the
    machine-wide scope, and a test that assigned it overwrote the developer's
    stored username. Assigning it here is safe only because
    `_require_isolated()` has already established that the write cannot reach the
    real store; the assertion order is the point.
    """
    _require_isolated()
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    # No file I/O: only the setter path matters, and it needs just the internal
    # options dict (`username` is not in it, so it falls through to the store)
    # and a code for the per-series branch it does not take.
    series = Series.__new__(Series)
    series.options = {}
    series.code = "isolationprobe"
    series._settings_store = QSettingsStore()
    assert "username" in Series.qsettings_defaults, (
        "username is expected to be a global-scope option; if it moved to the "
        "per-series scope this test is checking the wrong thing"
    )

    series.user = "isolation-probe-user"

    assert QSettingsStore().value(None, "username", str) == "isolation-probe-user"
    assert _under_root(QSettingsStore()._settings(None).fileName())


def test_the_recently_opened_series_route_is_isolated():
    """Incident 3, at the option layer.

    `MainWindow.openSeries` calls `addToRecentSeries`, which is
    `setOption("recently_opened_series", ...)` on the global scope, so every
    `main_window` fixture build used to prepend a `tmp_path` to the developer's
    real recents list. `last_folder` travels the same way.
    """
    _require_isolated()
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    store = QSettingsStore()
    store.set_value(None, "recently_opened_series", '["/tmp/probe.jser"]')
    store.set_value(None, "last_folder", "/tmp/probe")
    assert _under_root(store._settings(None).fileName())
    assert store.value(None, "last_folder", str) == "/tmp/probe"


def test_no_imported_module_still_holds_the_real_qsettings_class():
    """The sweep that makes this durable rather than a list of known routes.

    `from PySide6.QtCore import QSettings` copies the class into the importing
    module, so patching `PySide6.QtCore` alone is not enough for a module that
    already imported it. Star imports are the trap: `main_window.py` gets the
    name through `from .main_imports import *`, so it holds a reference of its
    own. If a module ever ends up holding the real class again, that module is a
    live route to the developer's settings and this fails with its name.
    """
    holders = []
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        try:
            bound = getattr(module, "QSettings", None)
        except Exception:  # pragma: no cover - defensive
            continue
        if bound is qi._real_qsettings:
            holders.append(name)
    assert not holders, (
        "these imported modules hold the real QSettings class and can reach the "
        f"developer's settings: {sorted(holders)}"
    )


def test_the_production_call_sites_resolve_to_the_isolated_class():
    """Import every module that constructs a `QSettings` and check what it holds.

    Enumerated from `git grep QSettings(` rather than discovered, so a new call
    site in a new module does not quietly get left out of the check: the sweep
    above is what covers that case, and this is what pins the known ones.
    """
    import importlib

    modules = (
        "PyReconstruct.modules.gui.dialog.file_dialog",
        "PyReconstruct.modules.gui.dialog.whats_new",
        "PyReconstruct.modules.gui.palette.mouse_palette",
        "PyReconstruct.modules.gui.main.main_imports",
        "PyReconstruct.modules.gui.main.main_window",
    )
    for name in modules:
        module = importlib.import_module(name)
        bound = getattr(module, "QSettings", None)
        assert bound is not None, f"{name} no longer binds QSettings"
        assert bound is not qi._real_qsettings, name
        assert _under_root(bound("KHLab", "PyReconstruct").fileName()), name


def test_whats_new_module_constants_still_name_the_real_domain():
    """The redirect changes the *location*, not the organization/application names.

    Worth pinning: swapping the names to a test-only pair was the other candidate
    mechanism, and it would have made every settings key the app reads at runtime
    invisible to these tests while looking like it worked.
    """
    from PyReconstruct.modules.gui.dialog import whats_new

    assert (whats_new.ORG, whats_new.APP) == ("KHLab", "PyReconstruct")


# --- the guard ----------------------------------------------------------------


def _guard_on(tmp_path):
    directory = tmp_path / "prefs"
    directory.mkdir()
    return qi.RealSettingsGuard(str(directory), "com.example.Watched"), directory


def test_guard_is_quiet_when_nothing_changes(tmp_path):
    guard, directory = _guard_on(tmp_path)
    (directory / "com.example.Watched.plist").write_bytes(
        plistlib.dumps({"username": "real", "theme": "dark"})
    )
    (directory / "unrelated.plist").write_bytes(plistlib.dumps({"other": 1}))
    guard.snapshot()
    assert guard.diff() == []


def test_guard_reports_a_modified_file_and_names_the_keys(tmp_path):
    guard, directory = _guard_on(tmp_path)
    watched = directory / "com.example.Watched.plist"
    watched.write_bytes(plistlib.dumps({"username": "real", "theme": "dark"}))
    guard.snapshot()

    watched.write_bytes(plistlib.dumps({"username": "real", "last_folder": "/tmp/x"}))
    problems = guard.diff()

    assert len(problems) == 1
    assert "modified" in problems[0]
    assert "last_folder" in problems[0]      # added
    assert "theme" in problems[0]            # removed


def test_guard_reports_a_value_change_with_the_same_keys(tmp_path):
    """The `series.user` shape: one key, overwritten. No key set change at all."""
    guard, directory = _guard_on(tmp_path)
    watched = directory / "com.example.Watched.plist"
    watched.write_bytes(plistlib.dumps({"username": "real"}))
    guard.snapshot()

    watched.write_bytes(plistlib.dumps({"username": "clobbered"}))
    problems = guard.diff()

    assert len(problems) == 1
    assert "same key set, changed values" in problems[0]


def test_guard_reports_a_newly_created_domain(tmp_path):
    """A per-series domain is created on first write, so an appearing file is a
    failure and not just a changed one.
    """
    guard, directory = _guard_on(tmp_path)
    guard.snapshot()
    (directory / "com.example.Watched-someseries.plist").write_bytes(
        plistlib.dumps({"autobackup": False})
    )
    problems = guard.diff()
    assert len(problems) == 1
    assert "created" in problems[0]
    assert "autobackup" in problems[0]


def test_guard_reports_a_deleted_file(tmp_path):
    guard, directory = _guard_on(tmp_path)
    watched = directory / "com.example.Watched.plist"
    watched.write_bytes(plistlib.dumps({"username": "real"}))
    guard.snapshot()
    watched.unlink()
    assert any("deleted" in p for p in guard.diff())


def test_guard_ignores_files_outside_the_domain_family(tmp_path):
    guard, directory = _guard_on(tmp_path)
    guard.snapshot()
    (directory / "com.apple.something.plist").write_bytes(plistlib.dumps({"a": 1}))
    assert guard.diff() == []


def test_guard_matches_the_domain_case_insensitively(tmp_path):
    """macOS treats `com.KHLab.PyReconstruct` and `com.khlab.PyReconstruct` as
    one store, so the watcher has to as well or half the family is unwatched.
    """
    guard, directory = _guard_on(tmp_path)
    guard.snapshot()
    (directory / "COM.EXAMPLE.watched-x.plist").write_bytes(plistlib.dumps({"a": 1}))
    assert any("created" in p for p in guard.diff())


def test_guard_catches_a_real_qsettings_write(tmp_path):
    """End to end, through Qt rather than a hand-written file.

    This is the proof that a genuine leak from the suite is still caught, and it
    exercises both halves at once: the digest notices the file changed, and the
    tripwire attributes the write to this process and to this test.

    The rogue write is a real `QSettings` write, on the real class, to a real
    settings file that the guard is watching. Pointed at `tmp_path` instead of
    the developer's Preferences directory, because demonstrating the guard by
    committing a test that writes the real store would be the fourth incident.
    `deliberate_bypass` is what stops this proof from failing the session it is
    proving: the record is asserted against and then dropped, leaving no
    residue.
    """
    import PySide6.QtCore as qtcore

    directory = tmp_path / "rogue"
    directory.mkdir()
    real = qi._real_qsettings
    real.setPath(real.Format.IniFormat, real.Scope.UserScope, str(directory))
    try:
        with qi.deliberate_bypass() as recorded:
            settings = real(
                real.Format.IniFormat, real.Scope.UserScope, "Watched", "Domain"
            )
            target = os.path.dirname(settings.fileName())
            guard = qi.RealSettingsGuard(target, "Domain")
            guard.snapshot()

            settings.setValue("username", "clobbered-by-a-test")
            settings.sync()

            problems = guard.diff()
            assert problems, f"guard missed a real write to {settings.fileName()}"
            assert "username" in problems[0]
    finally:
        # restore the session's isolation root, or every later test in this
        # session would resolve into tmp_path and the guard would be armed on it
        real.setPath(
            real.Format.IniFormat, real.Scope.UserScope, qi.isolation_root
        )
        assert _under_root(qi.resolved_path())
    del qtcore

    # the tripwire saw the same write, and knows who did it
    assert len(recorded) == 1, recorded
    assert recorded[0].method == "setValue"
    assert recorded[0].key == "username"
    assert recorded[0].path == str(directory / "Watched" / "Domain.ini")
    assert "test_guard_catches_a_real_qsettings_write" in recorded[0].test
    assert "setValue" in recorded[0].stack

    # and on that evidence the session fails, whatever the digest says
    level, message = qi.session_report(problems, tuple(recorded), root="/root")
    assert level == "fail"
    assert "wrote the real application settings" in message
    assert "test_guard_catches_a_real_qsettings_write" in message

    # the proof left nothing behind for the session-end check to trip on
    assert qi.recorded_bypasses() == ()


def test_the_tripwire_ignores_ordinary_isolated_writes():
    """Every settings write in the suite goes through the wrapped methods.

    The isolated subclass inherits them, so the tripwire has to let those
    through or the session would fail on its own redirect working correctly.
    """
    import PySide6.QtCore as qtcore

    with qi.deliberate_bypass() as recorded:
        settings = qtcore.QSettings(qi.ORG, qi.APP)
        settings.setValue("isolation_probe_tripwire", "landed")
        settings.sync()
        assert _under_root(settings.fileName())
    assert recorded == [], recorded


def test_the_tripwire_ignores_a_bypass_that_still_lands_in_the_root():
    """Reaching the real class is not itself pollution.

    `_install` also redirects the real class's own `IniFormat` path, so a
    bypass can still resolve inside the isolation root. Nothing real is written,
    so there is nothing to report, and reporting it would be a false alarm.
    """
    real = qi._real_qsettings
    with qi.deliberate_bypass() as recorded:
        settings = real(
            real.Format.IniFormat, real.Scope.UserScope, qi.ORG, "TripwireInRoot"
        )
        assert _under_root(settings.fileName())
        settings.setValue("probe", "landed")
        settings.sync()
    assert recorded == [], recorded


def test_the_tripwire_records_every_mutating_method(tmp_path):
    """`remove` and `clear` pollute as surely as `setValue` does.

    Incident one was a `clear()` plus an `allKeys()` rewrite, so a tripwire that
    only watched `setValue` would have missed the incident that started this.
    """
    real = qi._real_qsettings
    real.setPath(real.Format.IniFormat, real.Scope.UserScope, str(tmp_path))
    try:
        with qi.deliberate_bypass() as recorded:
            settings = real(
                real.Format.IniFormat, real.Scope.UserScope, "Watched", "Methods"
            )
            settings.setValue("kept", 1)
            settings.remove("kept")
            settings.clear()
            settings.sync()
    finally:
        real.setPath(
            real.Format.IniFormat, real.Scope.UserScope, qi.isolation_root
        )
        assert _under_root(qi.resolved_path())

    assert [r.method for r in recorded] == ["setValue", "remove", "clear"]


# --- attribution: what the end of the session says ----------------------------


def test_an_unattributed_change_warns_instead_of_failing():
    """The case that made this necessary: the application is open.

    A digest change with no recorded mutation cannot be the suite's doing, and
    the developer runs the suite with the application open, which writes its own
    preferences as it goes. Failing the run there blames him for something he
    did not do and cannot prevent, and a check that cries wolf during ordinary
    work is a check he will learn to ignore.
    """
    problems = [
        "modified: /Preferences/com.khlab.PyReconstruct.plist "
        "(same key set, changed values)"
    ]
    level, message = qi.session_report(problems, (), root="/root")
    assert level == "warn"
    assert "not the writer" in message
    assert "pgrep -fl PyReconstruct" in message
    assert "notification, not a" in message
    # it must not accuse the suite
    assert "this test session wrote" not in message


def test_an_unattributed_change_can_be_made_strict():
    """CI has no application running, so there any change is worth failing on."""
    problems = [
        "modified: /Preferences/com.khlab.PyReconstruct.plist "
        "(same key set, changed values)"
    ]
    level, message = qi.session_report(problems, (), root="/root", strict=True)
    assert level == "fail"
    assert qi.STRICT_ENV in message


@pytest.mark.parametrize(
    "value, expected",
    [("", False), ("0", False), ("false", False), ("no", False),
     ("1", True), ("true", True), ("yes", True)],
)
def test_strict_is_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv(qi.STRICT_ENV, value)
    assert qi.strict_requested() is expected


def test_strict_is_off_when_unset(monkeypatch):
    monkeypatch.delenv(qi.STRICT_ENV, raising=False)
    assert qi.strict_requested() is False


def test_a_quiet_session_reports_nothing():
    level, message = qi.session_report([], (), root="/root")
    assert level == "ok"
    assert message == ""


def test_a_recorded_mutation_fails_even_when_the_digest_is_clean():
    """`cfprefsd` need not have flushed by the time the session ends.

    The digest can miss a real write that is still sitting in the preferences
    daemon. The tripwire cannot, because it records the call itself, so a
    recorded mutation fails on its own evidence.
    """
    bypass = qi.Bypass(
        method="setValue",
        key="username",
        path="/Preferences/com.khlab.PyReconstruct.plist",
        test="tests/test_x.py::test_y (call)",
        stack="  stack\n",
    )
    level, message = qi.session_report([], (bypass,), root="/root")
    assert level == "fail"
    assert "tests/test_x.py::test_y" in message
    assert "username" in message


def test_the_session_note_is_printed_by_the_terminal_summary():
    """conftest reads this module's `terminal_note`, so it has to exist."""
    import conftest

    assert hasattr(conftest, "pytest_terminal_summary")
    assert hasattr(qi, "terminal_note")


def test_the_session_guard_is_armed_on_the_real_store():
    """The session-scoped guard watches the real domain family, not a copy.

    Cheap, and it is the assertion that would have caught the guard being
    pointed at the isolation root by accident, which would make it always pass.
    """
    assert qi.guard is not None
    assert not _under_root(qi.guard.directory)
    assert qi.guard.prefix.lower().endswith("pyreconstruct")
    assert qi.guard.baseline is not None


# --- production is untouched --------------------------------------------------


def test_production_still_resolves_to_the_real_settings_location():
    """A real user's settings must still be the real ones.

    Has to run outside this process: in here the redirect is installed on
    purpose, so the check would be measuring the fixture. The subprocess loads
    no `conftest.py`, constructs the app's own domain, and only *reads*
    `fileName()`/`format()`, which touch nothing.
    """
    script = textwrap.dedent(
        """
        import os, sys
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QSettings

        s = QSettings("KHLab", "PyReconstruct")
        # read-only: fileName() and format() do not write
        print("FORMAT", s.format().name)
        print("PATH", s.fileName())
        print("NATIVE", QSettings.Format.NativeFormat.name)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    out = dict(
        line.split(" ", 1) for line in result.stdout.strip().splitlines()
    )
    assert out["FORMAT"] == out["NATIVE"], (
        "production should use the platform's native settings backend, got "
        f"format {out['FORMAT']}"
    )
    assert not _under_root(out["PATH"]), (
        "the isolation root leaked into a process that does not load the suite's "
        f"conftest: {out['PATH']}"
    )
    # and it is the app's own domain, wherever the platform puts it
    assert "PyReconstruct" in out["PATH"]


def test_isolation_needs_the_suite_conftest_to_be_active():
    """The redirect is test-only: importing the app does not install it.

    The companion to the test above. Imports a module that builds a `QSettings`
    and checks it did not somehow acquire the isolated class, which is what
    would happen if the mechanism had been put in the package rather than in
    `tests/`.
    """
    script = textwrap.dedent(
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyReconstruct.modules.gui.dialog import file_dialog
        print("CLASSNAME", file_dialog.QSettings.__name__)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "CLASSNAME QSettings" in result.stdout, result.stdout
    assert "Isolated" not in result.stdout


def test_the_interactive_profiler_redirects_qsettings_by_domain():
    """`benchmarks/profile_interactive.py` runs outside pytest, so nothing in
    this directory protects it. It has to redirect on its own.

    It used to set `XDG_CONFIG_HOME` and state in its docstring that the real
    user settings were "never read or written". That is false on macOS for the
    same measured reason `HOME=` is: the two-argument `QSettings(org, app)`
    constructor stays `NativeFormat` and goes through the platform store, which
    ignores `XDG_CONFIG_HOME` entirely. The script drives the real render loop,
    `Series.getOption` writes the default back on a miss, so every profiling run
    on macOS wrote the developer's own preferences.

    Source-level rather than behavioral: importing the module builds a scratch
    directory and pulls in Qt, and the property worth pinning is that the
    redirect is still there at all. A profiler that quietly loses it looks
    exactly like one that still has it.
    """
    profiler = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "benchmarks", "profile_interactive.py",
    )
    with open(profiler) as f:
        source = f.read()

    assert "QtCore.QSettings = " in source, (
        "profile_interactive.py no longer rebinds QSettings; it has no other "
        "protection, since tests/qsettings_isolation.py never loads for it"
    )
    assert "SCRATCH_ORG" in source and "SCRATCH_APP" in source

    # The old mechanism must not come back. Matched as an assignment, not as the
    # bare name: the module explains at length why the name does not work, and a
    # test that forbids the word would forbid the explanation.
    for setter in ('os.environ["XDG_CONFIG_HOME"] =',
                   "os.environ['XDG_CONFIG_HOME'] =",
                   'os.environ.setdefault("XDG_CONFIG_HOME"',
                   'os.environ["HOME"] =',
                   "setDefaultFormat("):
        assert setter not in source, (
            f"{setter} is back in profile_interactive.py. It does not redirect "
            "QSettings on macOS; it is on the list of scoping that looks like "
            "it worked and did not."
        )

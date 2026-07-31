"""The launch-time update check is on by default, and the guards around it hold.

``update_check_on_startup`` used to ship off, so the four things that keep the
check from being a nuisance had never actually run in the on state. Turning it on
is one character; these are the guards it now rests on, each driven through the
real ``MainWindow.checkForUpdatesStartup`` rather than a paraphrase of it:

1. **Frozen builds only.** A source checkout or a pip install must never call
   out, whatever the option says. The gate is an allowlist (``!= "frozen"``),
   not a denylist, so a third install kind added later is closed by default.
2. **Once per 24 hours**, on a single global key. Also: a stored value that is
   corrupt, or one written by a clock that was wrong, must not leave the check
   either firing every launch or -- the failure the clamp here fixes -- silently
   dead forever.
3. **Every failure is silent and non-blocking.** No network, a refused
   connection, a timeout, a 403 rate-limit, and malformed JSON each leave
   startup untouched. The 403 matters most: GitHub allows 60 anonymous requests
   an hour per address, and a lab shares one outbound address, so a rate-limited
   check must not retry.
4. **Nothing here writes the real settings.** The throttle is a genuine
   ``QSettings`` round-trip, exercised through the class the suite has already
   redirected, and the session tripwire is asserted directly at the end.

On (2), the future-stamp case is a fix, not just a test. ``time.time() - last <
24 * 3600`` reads a stamp *ahead of* now as "checked recently", so a machine that
writes the stamp before its clock syncs (a fresh install, a restored VM
snapshot), or any corrupt large value, disables the check until the clock catches
up -- for a big enough value, permanently, with the option still reading as on
and no way for the user to tell. Measured on the pre-fix code: a stamp of
``now + 1 year`` and a stamp of ``1e18`` both produced zero checks and left the
bad value in place. The gate is now ``0 <= elapsed < 24 * 3600``, so a future
stamp is stale, the check runs, and the stamp is rewritten to now.

On (3), the network is faked at ``urllib.request.urlopen``. Every test that
reaches the transport asserts the fake was actually called, so a test that
stopped exercising the transport fails rather than passing vacuously, and no
test in here can reach GitHub.
"""

import email.message
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.request

import pytest

from PySide6.QtCore import QSettings

import qsettings_isolation

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.backend.updater import install_info as II
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.main import main_window as MW

ORG = "KHLab"
APP = "PyReconstruct"
STAMP_KEY = "last_update_check_epoch"
DAY = 24 * 3600

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


# --------------------------------------------------------------------------- #
# stand-ins
# --------------------------------------------------------------------------- #

class _Series:
    """The slice of ``Series`` the startup check reads.

    A real ``Series`` is used where the *option plumbing* is what is under test
    (see the default section below). Here the options are the input to a gate,
    so a dict is the honest stand-in and keeps the gate tests independent of how
    options are stored.
    """

    def __init__(self, **options):
        self.options = {"update_check_on_startup": True, "update_channel": "release"}
        self.options.update(options)
        self.reads = []

    def getOption(self, name, get_default=False):
        self.reads.append(name)
        value = self.options[name]
        if isinstance(value, Exception):
            raise value
        return value


class _Window:
    """A stand-in for ``MainWindow`` carrying only what the startup check touches.

    ``checkForUpdatesStartup`` is called unbound against this. Building a real
    ``MainWindow`` would bring up the whole widget tree and its own launch
    timers, none of which is under test: what is under test is four lines of
    gating and one dispatch.

    ``dispatch`` stands in for the thread pool. The real ``_runUpdateCheck``
    hands the work to a ``Worker`` whose ``run()`` catches everything and routes
    it to ``on_error``; a test that wants a failing check calls ``on_error``
    itself, which is the same contract without a thread.
    """

    def __init__(self, series=None, dispatch=None):
        self.series = series
        self.dispatched = []
        self.surfaced = []
        self._dispatch = dispatch

    def _runUpdateCheck(self, channel, on_result, on_error):
        self.dispatched.append(channel)
        if self._dispatch is not None:
            self._dispatch(self, channel, on_result, on_error)

    def _onStartupCheck(self, info, channel):
        self.surfaced.append((info, channel))


def _launch(window, kind="frozen", monkeypatch=None):
    """One application launch: run the real startup check with ``install_kind``
    reporting ``kind``."""
    monkeypatch.setattr(MW, "install_kind", lambda: kind)
    MW.MainWindow.checkForUpdatesStartup(window)
    return window


# --------------------------------------------------------------------------- #
# the throttle stamp, through the (already redirected) real QSettings
# --------------------------------------------------------------------------- #

class _Stamp:
    """Read/write the throttle stamp the way the application does.

    Deliberately the real ``QSettings`` class and not a dict. The throttle is a
    ``QSettings`` round-trip, and the backend hands the value back as a *string*,
    which is exactly the coercion the ``float()`` call has to survive; a dict
    would return whatever Python object the test put in and prove less.
    ``tests/qsettings_isolation.py`` redirected the class at import time, so
    every write here lands in the session's throwaway root.
    """

    def __init__(self, app=APP):
        self.app = app

    def _settings(self):
        return QSettings(ORG, self.app)

    def clear(self):
        self._settings().remove(STAMP_KEY)

    def set(self, value):
        self._settings().setValue(STAMP_KEY, value)

    def raw(self):
        return self._settings().value(STAMP_KEY, None)

    def present(self):
        return self._settings().contains(STAMP_KEY)

    def seconds(self):
        return float(self.raw())


@pytest.fixture
def stamp():
    """A clean throttle stamp before and after each test.

    The stamp is one global key, so it outlives a test unless it is cleared;
    leaving it set would silently throttle whatever ran next.
    """
    s = _Stamp()
    s.clear()
    yield s
    s.clear()


# --------------------------------------------------------------------------- #
# 0. the default itself
# --------------------------------------------------------------------------- #

def test_the_shipped_default_is_on():
    """The one character this whole file exists to hold up."""
    assert default_settings["update_check_on_startup"] is True


def _real_series(tmp_path):
    """A real Series on a throwaway settings store, for the option plumbing."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def test_an_install_with_nothing_stored_reads_the_check_as_on(tmp_path):
    """The default has to arrive through ``getOption``, not just sit in a dict.

    ``getOption`` resolves an unstored option against ``qsettings_defaults``,
    which is a copy of ``default_settings`` taken at class-definition time, so
    the two can drift.
    """
    series = _real_series(tmp_path)
    assert series.getOption("update_check_on_startup") is True


def test_a_stored_choice_still_wins_over_the_default(tmp_path):
    """Turning the default on must not overrule someone who turned it off.

    ``getOption`` prefers a stored value to the default, and it *persists* the
    default on first read, so an install that has already run stores its answer
    and keeps it across an upgrade. The switch in Series > Options is what moves
    it, in both directions.
    """
    series = _real_series(tmp_path)
    series.setOption("update_check_on_startup", False)
    assert series.getOption("update_check_on_startup") is False
    series.setOption("update_check_on_startup", True)
    assert series.getOption("update_check_on_startup") is True


# --------------------------------------------------------------------------- #
# 1. the frozen-build gate
# --------------------------------------------------------------------------- #

def test_this_checkout_reports_itself_as_a_source_install():
    """The gate is closed here without anything being patched.

    Every other test in this section patches ``install_kind``, which proves the
    gate reads it but says nothing about what it returns in a real source tree.
    This is that half: the suite runs from a checkout, so the honest answer is
    "source", and the check is therefore off for anyone running this way.
    """
    from PyReconstruct.modules.constants.frozen import is_frozen

    assert is_frozen() is False
    assert II.install_kind() == "source"


@pytest.mark.parametrize("kind", ["source", "pip", "wheel", "", "FROZEN"])
def test_an_install_that_is_not_frozen_never_checks(monkeypatch, stamp, kind):
    """A source checkout or a pip install must not call out, option or no option.

    Parametrized past the two values ``install_kind`` returns today on purpose:
    the gate is written as an allowlist, so an install kind introduced later is
    closed until someone opens it deliberately. ``"FROZEN"`` pins the comparison
    as case-sensitive.
    """
    window = _launch(_Window(_Series(update_check_on_startup=True)),
                     kind=kind, monkeypatch=monkeypatch)

    assert window.dispatched == []
    assert not stamp.present()   # the gate returns before the stamp is touched


def test_a_frozen_build_with_the_option_on_checks(monkeypatch, stamp):
    """The positive control: without this, every guard above passes vacuously."""
    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]


def test_the_option_off_still_wins_on_a_frozen_build(monkeypatch, stamp):
    """The switch in Series > Options is the whole opt-out, so it has to hold."""
    window = _launch(_Window(_Series(update_check_on_startup=False)),
                     monkeypatch=monkeypatch)

    assert window.dispatched == []
    assert not stamp.present()


def test_a_launch_with_no_series_open_does_not_check(monkeypatch, stamp):
    """The option lives on the series, so there is nothing to read yet."""
    window = _launch(_Window(series=None), monkeypatch=monkeypatch)

    assert window.dispatched == []
    assert not stamp.present()


def test_the_channel_the_check_runs_on_is_the_stored_one(monkeypatch, stamp):
    """Beta users have to be offered beta builds, or the check misinforms them."""
    window = _launch(_Window(_Series(update_channel="prerelease")),
                     monkeypatch=monkeypatch)

    assert window.dispatched == ["prerelease"]


# --------------------------------------------------------------------------- #
# 2. the 24-hour throttle
# --------------------------------------------------------------------------- #

def test_a_second_launch_inside_the_window_does_not_check(monkeypatch, stamp):
    """Two launches in a morning is one request, not two."""
    first = _launch(_Window(_Series()), monkeypatch=monkeypatch)
    assert first.dispatched == ["release"]
    assert stamp.present()

    second = _launch(_Window(_Series()), monkeypatch=monkeypatch)
    assert second.dispatched == []


def test_a_launch_after_the_window_checks_again(monkeypatch, stamp):
    """The throttle is a delay, not an off switch."""
    stamp.set(time.time() - DAY - 1)

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]


@pytest.mark.parametrize("age,expected", [
    (0, []),                # just now
    (DAY - 60, []),         # a minute short of the window
    (DAY + 60, ["release"]),  # a minute past it
])
def test_the_window_is_twenty_four_hours(monkeypatch, stamp, age, expected):
    """Pins the size of the window, so shortening it is a deliberate act."""
    stamp.set(time.time() - age)

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == expected


def test_the_stamp_is_a_single_global_key(monkeypatch, stamp):
    """One key for the install, not one per series.

    Per-series would mean the throttle resets every time someone opens a
    different series, which for a lab machine sharing an outbound address is the
    rate limit again by another route.
    """
    _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert _Stamp(APP).present()
    assert not _Stamp(f"{APP}-shapes1").present()
    assert not _Stamp(f"{APP}-someothercode").present()


@pytest.mark.parametrize("stored", ["banana", "", "  ", "nan-ish", "1.2.3"])
def test_an_unreadable_stamp_checks_once_and_then_throttles(monkeypatch, stamp, stored):
    """A corrupt stored value must not mean "check every launch, forever".

    Failing open once is right -- the alternative is a stored typo disabling the
    feature -- but only if the launch that fails open also *repairs* the value.
    Both halves are asserted, as a sequence of two launches, because the first
    on its own is the bug.
    """
    stamp.set(stored)

    first = _launch(_Window(_Series()), monkeypatch=monkeypatch)
    assert first.dispatched == ["release"]
    assert stamp.seconds() == pytest.approx(time.time(), abs=30)

    second = _launch(_Window(_Series()), monkeypatch=monkeypatch)
    assert second.dispatched == []


def test_a_missing_stamp_checks(monkeypatch, stamp):
    """First launch on a new install: nothing stored, so nothing to wait for."""
    assert not stamp.present()

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]


@pytest.mark.parametrize("offset,label", [
    (3600, "an hour ahead"),
    (365 * DAY, "a year ahead"),
])
def test_a_stamp_from_the_future_does_not_disable_the_check(monkeypatch, stamp,
                                                            offset, label):
    """A clock that was wrong when the stamp was written must not kill the check.

    ``time.time() - last`` goes negative for a stamp ahead of now, and negative
    is less than a day, so the pre-fix gate read it as "checked recently" and
    returned. A machine that syncs its clock after login, or a restored VM
    snapshot, writes exactly that stamp; when the clock corrects, the check is
    off until the stamp comes back into the past. There is no symptom: the
    option still reads as on.

    Measured on the pre-fix code, both offsets here produced zero checks and
    left the bad stamp in place.
    """
    stamp.set(time.time() + offset)

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"], f"stamp {label} disabled the check"
    # and it healed itself: the stamp is back in the present, so the next launch
    # throttles normally instead of checking again.
    assert stamp.seconds() == pytest.approx(time.time(), abs=30)
    assert _launch(_Window(_Series()), monkeypatch=monkeypatch).dispatched == []


def test_an_absurd_future_stamp_does_not_disable_the_check_permanently(monkeypatch,
                                                                       stamp):
    """The unbounded version of the case above: a corrupt *numeric* value.

    ``1e18`` parses as a float, so the ``except (TypeError, ValueError)`` branch
    never sees it. Read as a timestamp it is roughly thirty billion years from
    now, which under the pre-fix gate is a permanent, silent off switch.
    """
    stamp.set(1e18)

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]
    assert stamp.seconds() == pytest.approx(time.time(), abs=30)


def test_a_negative_stamp_checks(monkeypatch, stamp):
    """Far enough in the past is still the past; nothing special is needed."""
    stamp.set(-1)

    window = _launch(_Window(_Series()), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]


def test_the_stamp_is_written_before_the_check_is_dispatched(monkeypatch, stamp):
    """The structural reason a failing check cannot become a retry loop.

    The day is spent when the check is *attempted*, not when it succeeds. If the
    stamp were written on success instead, a network that is down, or an address
    that is rate limited, would mean a fresh request on every single launch --
    which is the state that earns the rate limit in the first place.
    """
    seen = {}

    def dispatch(window, channel, on_result, on_error):
        seen["stamped"] = _Stamp().present()

    _launch(_Window(_Series(), dispatch=dispatch), monkeypatch=monkeypatch)

    assert seen["stamped"] is True


# --------------------------------------------------------------------------- #
# 3. every failure is silent and non-blocking
# --------------------------------------------------------------------------- #

def _http_error(code, rate_limit_remaining=None):
    headers = email.message.Message()
    if rate_limit_remaining is not None:
        headers["X-RateLimit-Remaining"] = rate_limit_remaining
    return urllib.error.HTTPError(
        U.RELEASES_URL, code, "boom", headers, io.BytesIO(b""),
    )


class _Body:
    """A minimal stand-in for the object ``urlopen`` returns."""

    def __init__(self, payload):
        self._payload = payload

    def read(self, *args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


#: Every way the launch-time check can fail on the wire, and what the transport
#: is supposed to turn it into. The message is asserted loosely -- it is user
#: copy and may be reworded -- but it has to name the situation.
TRANSPORT_FAILURES = [
    pytest.param(urllib.error.URLError("[Errno 8] nodename nor servname provided"),
                 "reach", id="no-network"),
    pytest.param(urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
                 "reach", id="connection-refused"),
    pytest.param(TimeoutError("timed out"), "reach", id="timeout"),
    pytest.param(_http_error(403, rate_limit_remaining="0"), "rate limit",
                 id="rate-limited-403"),
    pytest.param(_http_error(403), "403", id="plain-403"),
    pytest.param(_http_error(500), "500", id="server-error"),
    pytest.param(json.JSONDecodeError("no", "<html>not json", 0), "unreadable",
                 id="malformed-json"),
]


@pytest.fixture
def transport(monkeypatch):
    """Replace the network with a scripted one, and count what it is asked for.

    Patched at ``urllib.request.urlopen``, which is the single call the updater
    makes; nothing in this file can reach GitHub. Every test using this asserts
    on ``calls``, so a test that stops exercising the transport fails rather
    than passing on a request it never made.
    """

    class Transport:
        def __init__(self):
            self.calls = []
            self.raises = None
            self.payload = b"[]"

        def __call__(self, req, timeout=None):
            self.calls.append(getattr(req, "full_url", req))
            if self.raises is not None:
                raise self.raises
            return _Body(self.payload)

    fake = Transport()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.mark.parametrize("error,expected_phrase", TRANSPORT_FAILURES)
def test_every_transport_failure_becomes_a_readable_runtime_error(transport, error,
                                                                  expected_phrase):
    """One exception type out of the transport, whatever went wrong underneath.

    The startup path discards the exception, so the *type* only matters for the
    manual check, which prints it. What matters here is that nothing exotic --
    a raw socket error, a JSON decode error -- escapes the transport to be
    handled by code that never anticipated it.
    """
    transport.raises = error

    with pytest.raises(RuntimeError) as excinfo:
        U.fetch_releases()

    assert transport.calls, "the transport was never called"
    assert expected_phrase.lower() in str(excinfo.value).lower()


def test_a_rate_limited_response_names_the_limit(transport):
    """The 403 users actually hit, worded so the manual check can explain it."""
    transport.raises = _http_error(403, rate_limit_remaining="0")

    with pytest.raises(RuntimeError) as excinfo:
        U.fetch_releases()

    message = str(excinfo.value)
    assert "60" in message and "rate limit" in message.lower()


def _failing_dispatch(error):
    """A ``_runUpdateCheck`` that runs the real check inline and fails like the
    worker does: the exception is caught and handed to ``on_error``."""

    def dispatch(window, channel, on_result, on_error):
        try:
            on_result(U.check_for_update(channel))
        except Exception as exc:      # what Worker.run does, minus the thread
            on_error(exc)

    del error
    return dispatch


@pytest.mark.parametrize("error,_phrase", TRANSPORT_FAILURES)
def test_startup_is_unaffected_by_any_transport_failure(monkeypatch, stamp,
                                                        transport, error, _phrase):
    """The whole point of the guard: a failed background check is a non-event.

    Nothing raises out of ``checkForUpdatesStartup``, nothing is put on screen,
    and no upgrade is surfaced.
    """
    transport.raises = error
    shown = []
    monkeypatch.setattr(MW, "notify", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(MW, "notifyConfirm", lambda *a, **k: shown.append(a) or True)

    window = _launch(_Window(_Series(), dispatch=_failing_dispatch(error)),
                     monkeypatch=monkeypatch)

    assert transport.calls, "the check never reached the transport"
    assert window.dispatched == ["release"]
    assert window.surfaced == []
    assert shown == []


def test_a_rate_limited_launch_makes_one_request_and_does_not_retry(monkeypatch,
                                                                    stamp,
                                                                    transport):
    """The case that matters most, because a lab shares one outbound address.

    A 403 is swallowed exactly like any other failure, and -- because the stamp
    was already spent -- the next launch does not go back for another. Three
    launches, one request. Without the throttle this is the loop that keeps an
    address at the limit indefinitely.
    """
    transport.raises = _http_error(403, rate_limit_remaining="0")
    dispatch = _failing_dispatch(None)

    for _ in range(3):
        window = _launch(_Window(_Series(), dispatch=dispatch), monkeypatch=monkeypatch)
        assert window.surfaced == []

    assert len(transport.calls) == 1


def test_a_dispatch_that_raises_synchronously_does_not_escape(monkeypatch, stamp):
    """The outer guard, for anything that goes wrong before the thread starts.

    Constructing the pool, or resolving the channel, happens on the GUI thread
    during startup, so it is outside the worker's own ``try``. If it raised it
    would reach the global exception hook and put an error window in front of a
    user who was only opening the application.
    """

    def dispatch(window, channel, on_result, on_error):
        raise RuntimeError("pool exploded")

    window = _launch(_Window(_Series(), dispatch=dispatch), monkeypatch=monkeypatch)

    assert window.dispatched == ["release"]


def test_an_option_lookup_that_raises_does_not_escape(monkeypatch, stamp):
    """A corrupt options store must not stop the application opening."""
    series = _Series(update_channel=RuntimeError("settings are unreadable"))

    _launch(_Window(series), monkeypatch=monkeypatch)   # must not raise


def test_a_successful_check_still_surfaces_an_upgrade(monkeypatch, stamp, transport):
    """The failure guards must not have made the check inert.

    Everything above asserts something does *not* happen, so this is the test
    that fails if the check were quietly disabled altogether: a real payload,
    through the real ``check_for_update``, reaching ``_onStartupCheck``.
    """
    monkeypatch.setattr(II, "platform_asset_tag", lambda: "Windows-x86_64")
    monkeypatch.setattr(II, "current_version", lambda: U.Version("1.20.0"))
    transport.payload = json.dumps([{
        "tag_name": "v1.21.0",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": "PyReconstruct-1.21.0-Windows-x86_64.exe"}],
    }]).encode()

    def dispatch(window, channel, on_result, on_error):
        on_result(U.check_for_update(channel))

    window = _launch(_Window(_Series(), dispatch=dispatch), monkeypatch=monkeypatch)

    assert transport.calls
    info, channel = window.surfaced[0]
    assert (info["status"], info["remote_version"], channel) == ("newer", "1.21.0",
                                                                "release")


# --------------------------------------------------------------------------- #
# 4. no settings pollution
# --------------------------------------------------------------------------- #

def test_the_throttle_writes_only_inside_the_isolation_root(monkeypatch, stamp):
    """The stamp is a real ``QSettings`` write, so it has to be a redirected one.

    Two claims, because either alone is weak: the domain the startup check
    addresses resolves inside the session's throwaway root, and the session
    tripwire -- which records any mutating call reaching the real class -- stays
    empty across a launch that definitely writes.
    """
    if not qsettings_isolation.installed:
        pytest.skip("Qt not importable, nothing to isolate")

    before = len(qsettings_isolation.recorded_bypasses())

    _launch(_Window(_Series()), monkeypatch=monkeypatch)

    path = os.path.abspath(QSettings(ORG, APP).fileName())
    assert path.startswith(os.path.abspath(qsettings_isolation.isolation_root))
    assert stamp.present()
    assert len(qsettings_isolation.recorded_bypasses()) == before

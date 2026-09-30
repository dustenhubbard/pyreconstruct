"""The two update feeds are strict: nothing is ever offered across channels.

PyReconstruct (stable) and PyReconstruct Dev (nightly) install side by side as
two apps. Each follows one channel, pinned by the build (``pinned_channel``),
and the rule since 2026-09-27 is the one T3 Code uses: the stable app only ever
sees stable releases, the Dev app only ever sees nightlies.

That inverts the rule the file this replaced pinned (``_newer_of``, 2026-08-05),
under which the test channel fell back to the newest stable release when no
pre-release was newer. That fallback made sense when "Beta" was a per-series
setting on a single install. With two apps it is a bug: the Dev app was handed
the stable installer, which installs a second stable PyReconstruct beside Dev
instead of updating Dev, and the Dev app went on reporting the same update
forever. So the Dev app with no nightly published is offered nothing, on
purpose, and the callers read that as "no update" rather than as an error.

The feed is keyed twice. ``pick_release`` picks by the GitHub ``prerelease``
flag and never crosses; ``pick_asset`` then keys on the ``-Dev`` marker the
packaging scripts put after the platform tag, so even a mislabeled release
cannot hand one flavor the other flavor's installer.

Tag shapes: stable ``v1.23.0``, nightly ``v1.24.0.dev20260928`` (PEP 440 dev
versions), older test builds ``v1.23.0-beta-6`` (which ``packaging`` reads as
``1.23.0b6``). A ``.devN`` of the next release sorts above every beta of the
current one, so a Dev client on the last beta is moved onto nightlies.
"""
import pytest
from packaging.version import Version

from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.backend.updater import install_info as II


def _rel(tag, prerelease=False, draft=False, assets=()):
    """A GitHub release object, reduced to the keys the updater reads."""
    return {
        "tag_name": tag, "prerelease": prerelease, "draft": draft,
        "assets": [{"name": n, "browser_download_url": f"https://github.com/x/{n}"}
                   for n in assets],
    }


def _nightly(ver):
    """A nightly release with a Dev-flavor asset for every platform CI builds."""
    return _rel(f"v{ver}", prerelease=True, assets=[
        f"PyReconstruct-{ver}-Windows-x86_64-Dev-Setup.exe",
        f"PyReconstruct-{ver}-Windows-x86_64-Dev-Setup.exe.sha256",
        f"PyReconstruct-{ver}-macOS-arm64-Dev.dmg",
        f"PyReconstruct-{ver}-macOS-arm64-Dev.dmg.sha256",
        f"PyReconstruct-{ver}-macOS-x86_64-Dev.dmg",
        f"PyReconstruct-{ver}-Linux-installer-Dev.tar.gz",
    ])


def _stable(ver):
    return _rel(f"v{ver}", assets=[
        f"PyReconstruct-{ver}-Windows-x86_64-Setup.exe",
        f"PyReconstruct-{ver}-Windows-x86_64-Setup.exe.sha256",
        f"PyReconstruct-{ver}-macOS-arm64.dmg",
        f"PyReconstruct-{ver}-macOS-x86_64.dmg",
        f"PyReconstruct-{ver}-Linux-installer.tar.gz",
    ])


def _beta(ver, n):
    """An old-style test build, `vX.Y.Z-beta-N`, with the Dev assets it shipped."""
    public = f"{ver}b{n}"
    return _rel(f"v{ver}-beta-{n}", prerelease=True, assets=[
        f"PyReconstruct-{public}-Windows-x86_64-Dev-Setup.exe",
        f"PyReconstruct-{public}-macOS-arm64-Dev.dmg",
    ])


def _tags(releases, channel):
    picked = U.pick_release(releases, channel)
    return picked["tag_name"] if picked else None


@pytest.fixture
def on_mac_arm(monkeypatch):
    monkeypatch.setattr(II, "platform_asset_tag", lambda: "macOS-arm64")


def _client(monkeypatch, version):
    monkeypatch.setattr(II, "current_version", lambda: Version(version))


# ---------------------------------------------------------------------------
# pick_release: the flag decides, and nothing crosses
# ---------------------------------------------------------------------------

def test_nightly_is_offered_nothing_when_no_prerelease_exists():
    """The Dev app before the first nightly of a cycle: no offer, not stable."""
    live = [_rel("v1.23.0"), _rel("v1.22.1"), _rel("v1.22.0")]

    assert _tags(live, "prerelease") is None
    assert _tags(live, "release") == "v1.23.0"


def test_nightly_is_not_offered_a_newer_stable_release():
    """A stable release newer than every nightly still stays on its own feed."""
    live = [_rel("v1.24.0"), _rel("v1.24.0.dev20260928", prerelease=True), _rel("v1.23.0")]

    assert _tags(live, "prerelease") == "v1.24.0.dev20260928"
    assert _tags(live, "release") == "v1.24.0"


def test_stable_never_offers_a_prerelease():
    live = [_rel("v1.24.0.dev20260928", prerelease=True), _rel("v1.23.0")]

    assert _tags(live, "release") == "v1.23.0"


def test_stable_with_only_prereleases_published_is_offered_nothing():
    live = [_rel("v1.24.0.dev20260928", prerelease=True), _rel("v1.23.0-beta-6", prerelease=True)]

    assert _tags(live, "release") is None


def test_the_newest_nightly_wins_over_older_nightlies_and_betas():
    live = [
        _rel("v1.24.0.dev20260929", prerelease=True),
        _rel("v1.24.0.dev20260928", prerelease=True),
        _rel("v1.23.0"),
        _rel("v1.23.0-beta-6", prerelease=True),
    ]

    assert _tags(live, "prerelease") == "v1.24.0.dev20260929"


def test_drafts_are_ignored_on_both_channels():
    live = [_rel("v1.99.0", draft=True), _rel("v1.99.0.dev20991231", prerelease=True, draft=True),
            _rel("v1.24.0.dev20260928", prerelease=True), _rel("v1.23.0")]

    assert _tags(live, "prerelease") == "v1.24.0.dev20260928"
    assert _tags(live, "release") == "v1.23.0"


def test_the_retired_rolling_tag_is_still_excluded_and_does_not_fall_through():
    """`ROLLING_TAG` is flagged prerelease but is not a nightly: skip it, and
    with nothing else on the channel the answer is None, never the stable."""
    live = [_rel(U.ROLLING_TAG, prerelease=True), _rel("v1.23.0")]

    assert _tags(live, "prerelease") is None
    assert _tags(live, "release") == "v1.23.0"


def test_an_unparseable_prerelease_tag_is_still_offered():
    """`pick_release` keys on the flag, not on the tag parsing; a hand-made tag
    is still this channel's newest release. Version comparison happens later,
    against the asset name, and reports 'unknown' if that fails too."""
    live = [_rel("v1.22.0-nightly-build", prerelease=True), _rel("v1.21.0")]

    assert _tags(live, "prerelease") == "v1.22.0-nightly-build"


@pytest.mark.parametrize("channel", ["prerelease", "release", "stable", "edge", "developer"])
def test_no_releases_at_all_returns_none(channel):
    """Including the legacy channel names, which `normalize_channel` remaps."""
    assert U.pick_release([], channel) is None
    assert U.pick_release(None, channel) is None


# ---------------------------------------------------------------------------
# pick_asset: the -Dev marker keeps the two flavors' installers apart
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg", True),
    ("PyReconstruct-1.24.0.dev20260928-Windows-x86_64-Dev-Setup.exe", True),
    ("PyReconstruct-1.24.0.dev20260928-Linux-installer-Dev.tar.gz", True),
    ("PyReconstruct-1.23.0b6-macOS-arm64-Dev.dmg", True),
    ("PyReconstruct-1.24.0.dev20260928-macOS-arm64.dmg", False),   # dev VERSION, stable flavor
    ("PyReconstruct-1.23.0-Windows-x86_64-Setup.exe", False),
    ("PyReconstruct-1.23.0-macOS-arm64-Development.dmg", False),  # not the marker
    ("", False),
    (None, False),
])
def test_is_dev_asset(name, expected):
    assert U.is_dev_asset(name) is expected


def test_dev_app_takes_only_the_dev_asset():
    rel = _rel("v1.24.0.dev20260928", prerelease=True, assets=[
        "PyReconstruct-1.24.0.dev20260928-macOS-arm64.dmg",
        "PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg",
        "PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg.sha256",
    ])
    assert U.pick_asset(rel, "macOS-arm64", dev=True)["name"].endswith("-Dev.dmg")
    assert U.pick_asset(rel, "macOS-arm64", dev=False)["name"].endswith("arm64.dmg")


def test_dev_app_gets_no_asset_from_a_stable_only_release():
    assert U.pick_asset(_stable("1.23.0"), "macOS-arm64", dev=True) is None
    assert U.pick_asset(_stable("1.23.0"), "Windows-x86_64", dev=True) is None


def test_stable_app_gets_no_asset_from_a_dev_only_release():
    assert U.pick_asset(_nightly("1.24.0.dev20260928"), "macOS-arm64") is None
    assert U.pick_asset(_nightly("1.24.0.dev20260928"), "Windows-x86_64", dev=False) is None


def test_the_marker_never_confuses_the_platform_match():
    """'-Dev' sits after the platform tag, so the arch tokens still resolve
    one asset each and the checksum sibling is still skipped."""
    rel = _nightly("1.24.0.dev20260928")
    assert U.pick_asset(rel, "macOS-arm64", dev=True)["name"] == \
        "PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg"
    assert U.pick_asset(rel, "macOS-x86_64", dev=True)["name"] == \
        "PyReconstruct-1.24.0.dev20260928-macOS-x86_64-Dev.dmg"
    assert U.pick_asset(rel, "Windows-x86_64", dev=True)["name"] == \
        "PyReconstruct-1.24.0.dev20260928-Windows-x86_64-Dev-Setup.exe"


# ---------------------------------------------------------------------------
# versions: nightly tags and asset names parse and order correctly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag,ver", [
    ("v1.24.0.dev20260928", "1.24.0.dev20260928"),
    ("v1.23.0", "1.23.0"),
    ("v1.23.0-beta-6", "1.23.0b6"),
    ("v1.21.0rc1", "1.21.0rc1"),
])
def test_tag_version_parses_every_tag_shape(tag, ver):
    assert U._tag_version(_rel(tag)) == Version(ver)


def test_tag_version_is_none_for_a_non_version_tag():
    assert U._tag_version(_rel(U.ROLLING_TAG)) is None
    assert U._tag_version(None) is None


@pytest.mark.parametrize("name,ver", [
    ("PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg", "1.24.0.dev20260928"),
    ("PyReconstruct-1.24.0.dev20260928-Windows-x86_64-Dev-Setup.exe", "1.24.0.dev20260928"),
    ("PyReconstruct-1.24.0.dev20260928-Linux-installer-Dev.tar.gz", "1.24.0.dev20260928"),
    ("PyReconstruct-1.23.0b6-macOS-arm64-Dev.dmg", "1.23.0b6"),
])
def test_asset_version_reads_nightly_names(name, ver):
    assert U.asset_version(name) == Version(ver)


@pytest.mark.parametrize("remote,local,expected", [
    ("1.24.0.dev20260928", "1.23.0b6", "newer"),          # last beta -> first nightly
    ("1.24.0.dev20260929", "1.24.0.dev20260928", "newer"),  # nightly -> next nightly
    ("1.24.0.dev20260928", "1.24.0.dev20260928", "same"),
    ("1.24.0.dev20260928", "1.24.0.dev20260929", "older"),
    ("1.24.0.dev20260928", "1.23.0", "newer"),
    ("1.24.0.dev20260928", "1.24.0", "older"),             # a dev sorts below its final
])
def test_compare_versions_orders_nightlies(remote, local, expected):
    assert U.compare_versions(Version(remote), Version(local)) == expected


def test_compare_versions_ignores_the_local_segment_on_a_nightly():
    remote = Version("1.24.0.dev20260928")
    local = Version("1.24.0.dev20260928+g1a2b3c4")
    assert U.compare_versions(remote, local) == "same"


# ---------------------------------------------------------------------------
# check_for_update: the five outcomes a real user sees
# ---------------------------------------------------------------------------

LIVE = [
    _nightly("1.24.0.dev20260929"),
    _nightly("1.24.0.dev20260928"),
    _stable("1.23.1"),
    _stable("1.23.0"),
    _beta("1.23.0", 6),
]


def test_dev_client_on_the_last_beta_is_offered_the_first_nightly(monkeypatch, on_mac_arm):
    _client(monkeypatch, "1.23.0b6")
    live = [_nightly("1.24.0.dev20260928"), _stable("1.23.0"), _beta("1.23.0", 6)]

    info = U.check_for_update("prerelease", releases=live)

    assert info["release"]["tag_name"] == "v1.24.0.dev20260928"
    assert info["asset"]["name"] == "PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg"
    assert (info["remote_version"], info["status"]) == ("1.24.0.dev20260928", "newer")


def test_dev_client_on_a_nightly_is_offered_the_next_nightly(monkeypatch, on_mac_arm):
    _client(monkeypatch, "1.24.0.dev20260928")

    info = U.check_for_update("prerelease", releases=LIVE)

    assert info["release"]["tag_name"] == "v1.24.0.dev20260929"
    assert info["asset"]["name"].endswith("-macOS-arm64-Dev.dmg")
    assert (info["remote_version"], info["status"]) == ("1.24.0.dev20260929", "newer")


@pytest.mark.parametrize("local", ["1.23.0b6", "1.24.0.dev20260928"])
def test_dev_client_is_not_offered_a_newer_stable(monkeypatch, on_mac_arm, local):
    """Stable 1.23.0 and 1.24.0 both outrank the client; neither is offered."""
    _client(monkeypatch, local)
    live = [_stable("1.24.0"), _stable("1.23.0")]

    info = U.check_for_update("prerelease", releases=live)

    assert info["release"] is None
    assert info["asset"] is None
    assert info["remote_version"] is None
    assert info["status"] == "unknown"


def test_dev_client_stays_on_its_own_older_build_rather_than_take_a_newer_stable(
    monkeypatch, on_mac_arm
):
    """Stables 1.23.0 and 1.24.0 outrank the last beta, and the last beta is the
    only nightly-channel release: the Dev app is told it is current, not moved
    onto stable."""
    _client(monkeypatch, "1.23.0b6")
    live = [_stable("1.24.0"), _stable("1.23.0"), _beta("1.23.0", 6)]

    info = U.check_for_update("prerelease", releases=live)

    assert info["release"]["tag_name"] == "v1.23.0-beta-6"
    assert info["asset"]["name"] == "PyReconstruct-1.23.0b6-macOS-arm64-Dev.dmg"
    assert info["status"] == "same"


def test_dev_client_with_no_nightly_published_is_offered_nothing(monkeypatch, on_mac_arm):
    """The state right after a stable ships and before the next nightly."""
    _client(monkeypatch, "1.23.0b6")

    info = U.check_for_update("prerelease", releases=[_stable("1.23.0"), _stable("1.22.1")])

    assert info["release"] is None
    assert info["asset"] is None
    assert info["status"] == "unknown"


def test_stable_client_is_not_offered_any_dev_or_prerelease(monkeypatch, on_mac_arm):
    _client(monkeypatch, "1.23.0")
    live = [_nightly("1.24.0.dev20260929"), _nightly("1.24.0.dev20260928"),
            _beta("1.24.0", 1), _stable("1.23.0")]

    info = U.check_for_update("release", releases=live)

    assert info["release"]["tag_name"] == "v1.23.0"
    assert info["asset"]["name"] == "PyReconstruct-1.23.0-macOS-arm64.dmg"
    assert info["status"] == "same"


def test_stable_client_is_offered_the_next_stable(monkeypatch, on_mac_arm):
    _client(monkeypatch, "1.23.0")

    info = U.check_for_update("release", releases=LIVE)

    assert info["release"]["tag_name"] == "v1.23.1"
    assert info["asset"]["name"] == "PyReconstruct-1.23.1-macOS-arm64.dmg"
    assert (info["remote_version"], info["status"]) == ("1.23.1", "newer")


def test_a_release_carrying_only_the_other_flavors_asset_is_not_an_offer(monkeypatch, on_mac_arm):
    """Belt and suspenders: a nightly whose Dev dmg failed to upload must not
    hand the Dev app the plain dmg that did (it would install a stable
    PyReconstruct beside Dev), and the stable app must not take a Dev dmg."""
    _client(monkeypatch, "1.23.0")
    odd = _rel("v1.24.0.dev20260928", prerelease=True,
               assets=["PyReconstruct-1.24.0.dev20260928-macOS-arm64.dmg"])
    assert U.check_for_update("prerelease", releases=[odd, _stable("1.23.0")])["asset"] is None

    odd2 = _rel("v1.23.1", assets=["PyReconstruct-1.23.1-macOS-arm64-Dev.dmg"])
    assert U.check_for_update("release", releases=[odd2, _stable("1.23.0")])["asset"] is None


def test_a_stored_legacy_channel_value_still_resolves_strictly(monkeypatch, on_mac_arm):
    """`developer`/`edge` remap to the nightly feed and `stable` to the stable
    one; the flavor match follows the remapped channel, not the raw string."""
    _client(monkeypatch, "1.23.0")
    assert U.check_for_update("developer", releases=LIVE)["asset"]["name"].endswith("-Dev.dmg")
    assert U.check_for_update("edge", releases=LIVE)["asset"]["name"].endswith("-Dev.dmg")
    assert U.check_for_update("stable", releases=LIVE)["asset"]["name"] == \
        "PyReconstruct-1.23.1-macOS-arm64.dmg"


# ---------------------------------------------------------------------------
# what the user reads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel,name", [
    ("release", "Stable"), ("prerelease", "Nightly"),
    ("stable", "Stable"), ("edge", "Nightly"), ("developer", "Nightly"),
    ("garbage", "Stable"), (None, "Stable"),
])
def test_channel_display_name(channel, name):
    assert U.channel_display_name(channel) == name


def test_newer_of_is_gone():
    """The fallback helper was the cross-channel path; it must not come back."""
    assert not hasattr(U, "_newer_of")


# ---------------------------------------------------------------------------
# what the manual check says when there is nothing to offer
# ---------------------------------------------------------------------------

def _window():
    """A bare stand-in for ``MainWindow`` carrying only the static log helper
    the no-offer path calls on ``self``. Nothing here needs a widget tree."""
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.main import main_window as MW
    return SimpleNamespace(
        _noteNothingToOffer=MW.MainWindow._noteNothingToOffer,
        clearUpdateNotice=lambda: None,  # the saved notice, not under test here
    )


def _manual_check(monkeypatch, info, channel):
    """Run the real ``_onCheckResult`` unbound, with ``notify`` captured."""
    from PyReconstruct.modules.gui.main import main_window as MW

    shown = []
    logged = []
    monkeypatch.setattr(MW, "notify", lambda msg, *a, **k: shown.append(msg))
    monkeypatch.setattr(
        "PyReconstruct.modules.backend.func.logging_setup.log_note",
        lambda msg: logged.append(msg),
    )
    MW.MainWindow._onCheckResult(_window(), info, channel, manual=True)
    return shown, logged


def test_manual_check_with_no_release_on_the_channel_says_no_update(monkeypatch, on_mac_arm):
    """A Dev app before the first nightly lands: an information notice, and a
    log line that says why. Not an error."""
    _client(monkeypatch, "1.23.0b6")
    info = U.check_for_update("prerelease", releases=[_stable("1.23.0")])

    shown, logged = _manual_check(monkeypatch, info, "prerelease")

    assert shown == ["No Nightly update is available for this app yet."]
    assert len(logged) == 1
    assert "nothing to offer on the Nightly channel" in logged[0]
    assert "no Nightly release is published" in logged[0]


def test_manual_check_with_a_release_but_no_installer_names_the_platform(monkeypatch):
    """An Intel Mac on an arm64-only stable release: the release exists, the
    installer for this platform and build does not."""
    monkeypatch.setattr(II, "platform_asset_tag", lambda: "macOS-x86_64")
    _client(monkeypatch, "1.23.0")
    arm_only = _rel("v1.23.1", assets=["PyReconstruct-1.23.1-macOS-arm64.dmg"])
    info = U.check_for_update("release", releases=[arm_only])

    shown, logged = _manual_check(monkeypatch, info, "release")

    assert shown == ["No installer is available for your platform on the Stable channel yet."]
    assert len(logged) == 1
    assert "newest Stable release is v1.23.1" in logged[0]


def test_manual_check_on_dev_with_a_stable_only_asset_names_the_platform(monkeypatch, on_mac_arm):
    """The nightly exists but its Dev dmg is missing: the platform wording,
    on the Nightly channel, and never the plain dmg."""
    _client(monkeypatch, "1.23.0b6")
    odd = _rel("v1.24.0.dev20260928", prerelease=True,
               assets=["PyReconstruct-1.24.0.dev20260928-macOS-arm64.dmg"])
    info = U.check_for_update("prerelease", releases=[odd])

    shown, _logged = _manual_check(monkeypatch, info, "prerelease")

    assert shown == ["No installer is available for your platform on the Nightly channel yet."]


def test_startup_check_with_nothing_to_offer_is_silent_and_logs_once(monkeypatch, on_mac_arm):
    from PyReconstruct.modules.gui.main import main_window as MW

    _client(monkeypatch, "1.23.0b6")
    info = U.check_for_update("prerelease", releases=[_stable("1.23.0")])
    shown, logged = [], []
    monkeypatch.setattr(MW, "notify", lambda msg, *a, **k: shown.append(msg))
    monkeypatch.setattr(MW, "notifyConfirm", lambda msg, *a, **k: shown.append(msg) or True)
    monkeypatch.setattr(
        "PyReconstruct.modules.backend.func.logging_setup.log_note",
        lambda msg: logged.append(msg),
    )

    MW.MainWindow._onStartupCheck(_window(), info, "prerelease")

    assert shown == []
    assert len(logged) == 1 and "nothing to offer on the Nightly channel" in logged[0]

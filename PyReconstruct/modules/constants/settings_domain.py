"""The global QSettings domain, flavored per installed app.

Two builds install side by side (PyReconstruct and PyReconstruct Dev), and the
agenda's isolation rule is that they never share stored state: the Dev
packaging stamps PYRECON_APP_NAME (packaging/rthook_flavor.py), and every
global QSettings domain in the app resolves through here so the two apps read
and write disjoint stores. The stable app, and any source run without the
variable, keeps the original KHLab/PyReconstruct domain untouched.

Read at call time, not import time, so tests can flip the environment without
reimporting, and so import order against the runtime hook cannot matter.
"""
import os

SETTINGS_ORG = "KHLab"


def settings_app():
    """The QSettings application name for this flavor."""
    return os.environ.get("PYRECON_APP_NAME", "PyReconstruct")


def settings_domain():
    """(org, app) — unpack into QSettings(*settings_domain())."""
    return SETTINGS_ORG, settings_app()


# One-time seed marker. Lives under meta/ so the seed never copies it (or any
# future bookkeeping key) between flavors.
SEED_MARKER = "meta/settings_seeded"

# Keys the seed must never copy between flavors, on top of meta/. The stable
# app suppresses the What's-new startup popup, but a Dev install exists to
# surface what changed, so inheriting the suppression silenced the popup on
# every fresh Dev install (found 2026-08-26). Mirrors
# WHATSNEW_SUPPRESS_KEY in gui/main/first_launch.py as a literal: constants
# cannot import from gui.
UNSEEDED_KEYS = frozenset({"suppress_whatsnew"})


def seed_flavor_settings_once(flavored=None, stable=None):
    """First launch of a flavored build: copy the stable app's stored settings.

    The Dev flavor reads its own QSettings domain so the two installed apps
    never share state. The cost surfaced immediately: a tester's first Dev
    launch came up with every option at its default, because nothing carried
    the settings the stable domain already held (Patrick's report,
    2026-08-25: auto-merge and rolling smoothing "did not carry over").

    Runs once: the marker key is written whether or not anything was copied,
    so a user who later clears a setting is not re-seeded behind their back.
    Copies only INTO a flavored domain, never out of one, and never touches
    meta/ keys. The stable app itself is a no-op. Returns True when a copy
    ran.

    ``flavored``/``stable`` are injectable for tests; production resolves
    both from the real domains.
    """
    org, app = settings_domain()
    if flavored is None:
        if app == "PyReconstruct":
            return False
        from PySide6.QtCore import QSettings
        flavored = QSettings(org, app)
    if flavored.value(SEED_MARKER, False):
        return False
    if stable is None:
        from PySide6.QtCore import QSettings
        stable = QSettings(org, "PyReconstruct")
    for key in stable.allKeys():
        if not key.startswith("meta/") and key not in UNSEEDED_KEYS:
            flavored.setValue(key, stable.value(key))
    flavored.setValue(SEED_MARKER, True)
    flavored.sync()
    return True

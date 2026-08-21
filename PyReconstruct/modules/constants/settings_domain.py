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

"""Which build this is, for the parts of PyReconstruct the stable app does not show.

Two things tell a Dev build from the stable one, and either is enough:

* the Dev app's environment. Its packaging stamps PYRECON_APP_NAME with
  "PyReconstruct Dev" (packaging/rthook_flavor.py; settings_domain.settings_app
  reads the same variable for the per-app settings);
* the version. A nightly (1.25.0.dev202610151111) and a source checkout of
  main (1.25.0.dev5+g0123abc) are dev releases; a stable build is a final
  version (1.24.0). An unreadable version is not a stable release either.

So a source checkout shows the Dev entries without setting anything, and the
stable app, built from a clean release tag with no flavor stamp, shows none.
Read at call time, so a test can set either signal without reimporting.
"""
from packaging.version import InvalidVersion, Version

from .settings_domain import settings_app


def running_version() -> str:
    """The version string of this build: the setuptools-scm version file, then
    the installed metadata, then "unknown" (repo_info)."""
    from .repo_info import _installed_version
    return _installed_version()


def is_dev_build() -> bool:
    """True for the Dev app, a nightly and a source checkout; False for the
    stable app."""
    if "Dev" in settings_app():
        return True
    try:
        return Version(running_version()).is_devrelease
    except InvalidVersion:
        return True

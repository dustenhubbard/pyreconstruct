"""Install-kind detection and version/platform helpers for the in-app updater.

Imported lazily by the Qt updater code. Relies on the canonical frozen detector
in ``PyReconstruct.modules.constants.frozen``.
"""

import sys
import platform as _platform
from importlib.metadata import version as _md_version

from packaging.version import Version, InvalidVersion

from PyReconstruct.modules.constants.frozen import is_frozen  # canonical detector


def install_kind() -> str:
    """'frozen' for a packaged build, else 'source' (git checkout or pip install)."""
    return "frozen" if is_frozen() else "source"


def current_version_str():
    """The running build's version string, or None if it can't be determined."""
    try:
        from PyReconstruct._version import version as scm_version  # written at build
        return scm_version
    except Exception:
        pass
    try:
        return _md_version("PyReconstruct")
    except Exception:
        return None


def current_version():
    """The running build's version as a packaging ``Version``, or None."""
    s = current_version_str()
    if not s:
        return None
    try:
        return Version(s)
    except InvalidVersion:
        return None


def os_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def arch_key() -> str:
    m = _platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return m or "unknown"


def platform_asset_tag() -> str:
    """Token embedded in release-asset names for this platform.

    Mirrors the CI naming convention, e.g. 'Windows-x86_64', 'macOS-arm64'.
    """
    label = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[os_key()]
    return f"{label}-{arch_key()}"

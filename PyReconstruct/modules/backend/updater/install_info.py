"""Install-kind detection and version/platform helpers for the in-app updater.

Imported lazily by the Qt updater code. Relies on the canonical frozen detector
in ``PyReconstruct.modules.constants.frozen``.
"""

import os
import sys
import platform as _platform
from pathlib import Path
from importlib.metadata import version as _md_version

from packaging.version import Version, InvalidVersion

from PyReconstruct.modules.constants.frozen import is_frozen  # canonical detector


# The marker each Linux installer leaves in its install folder.
# packaging/linux/install.sh writes LINUX_INSTALLER_MARKER beside the venv it
# builds; packaging/linux/install-appimage.sh writes APPIMAGE_MARKER beside
# the AppImage it downloads.
LINUX_INSTALLER_MARKER = ".pyreconstruct-install"
APPIMAGE_MARKER = ".appimage-install"

# Install kinds that update by running their installer again. The in-app
# updater never downloads for these; it names the command instead.
REINSTALL_KINDS = ("appimage", "linux-installer")


def _linux_installer_roots():
    """Folders where install.sh would have left its marker for this process.

    install.sh builds its venv at ``<root>/venv`` and writes the marker in
    ``<root>``, so the root is the parent of the venv (``sys.prefix``). The
    interpreter's own path is checked too, unresolved, since the venv's
    ``bin/python`` is a symlink to the system Python.
    """
    roots = [Path(sys.prefix).parent]
    try:
        roots.append(Path(sys.executable).parent.parent.parent)
    except Exception:
        pass
    return roots


def _appimage_roots():
    """Folders where install-appimage.sh would have left its marker.

    Beside the running AppImage when ``APPIMAGE`` names it, and the folder
    the installer uses for this flavor:
    ``${XDG_DATA_HOME:-~/.local/share}/<app name>``.
    """
    from PyReconstruct.modules.datatypes.series_owner import app_display_name

    roots = []
    image = os.environ.get("APPIMAGE")
    if image:
        roots.append(Path(image).parent)
    data_home = os.environ.get("XDG_DATA_HOME", "")
    if not os.path.isabs(data_home):  # the XDG spec ignores a relative value
        data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
    roots.append(Path(data_home) / app_display_name())
    return roots


def _has_marker(roots, name):
    for root in roots:
        try:
            if (root / name).is_file():
                return True
        except OSError:
            pass
    return False


def install_kind() -> str:
    """How this copy of PyReconstruct was installed.

    * ``'appimage'``: a frozen Linux build run as an AppImage (``APPIMAGE``
      is set) or installed by install-appimage.sh (its marker is present).
    * ``'frozen'``: any other packaged build.
    * ``'linux-installer'``: the venv install.sh built (its marker is in the
      venv's parent folder).
    * ``'source'``: a git checkout or a pip install.

    Frozen or not is decided first, because it is a fact about this process.
    The markers and ``APPIMAGE`` are not: ``APPIMAGE`` is inherited by
    anything an AppImage starts, and both installers can sit on one machine.
    So a source run never reads as an AppImage, and a frozen build never reads
    as the install.sh venv.
    """
    if is_frozen():
        if os_key() == "linux" and (
            os.environ.get("APPIMAGE") or _has_marker(_appimage_roots(), APPIMAGE_MARKER)
        ):
            return "appimage"
        return "frozen"
    if _has_marker(_linux_installer_roots(), LINUX_INSTALLER_MARKER):
        return "linux-installer"
    return "source"


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

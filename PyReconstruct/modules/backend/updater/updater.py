"""GitHub-Releases-based updater for frozen builds.

The frozen app can't ``pip install`` or use git, so "update" means: query the
GitHub Releases API, pick the installer asset for this platform/channel,
download it (with progress), optionally verify its SHA-256, then launch the
installer and quit. The dev/source update path stays in ``cli.py``.

Module-level imports are stdlib + ``packaging`` only (no Qt, no app imports), so
the pure functions here are unit-testable in isolation; ``install_info`` is
imported lazily inside the functions that need platform/version info.
"""

import os
import re
import json
import hashlib
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from packaging.version import Version, InvalidVersion

# Repo whose GitHub Releases the updater pulls installers from. Points at the
# fork for the POC (that is where CI publishes the installers); switch to
# "SynapseWeb/PyReconstruct" when this lands upstream. Kept as a separate
# literal (not imported from constants.gh_repo) so this module stays Qt-free.
GITHUB_REPO = "dustenhubbard/PyReconstruct"

RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
USER_AGENT = "PyReconstruct-updater"

# 'PyReconstruct-<version>-<Platform>-<arch>...' -> capture <version>.
_ASSET_VERSION_RE = re.compile(r"PyReconstruct-(?P<ver>.+?)-(?:Windows|macOS|Linux)\b")


class UpdateCancelled(Exception):
    """Raised when the user cancels a download mid-stream."""


# --- GitHub API ---------------------------------------------------------------

def _api_get(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise RuntimeError(
                "GitHub API rate limit reached (60 requests/hour for anonymous "
                "access). Please try again later."
            )
        raise RuntimeError(f"GitHub returned HTTP {e.code} while checking for updates.")
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Could not reach GitHub: {getattr(e, 'reason', e)}")
    except json.JSONDecodeError:
        raise RuntimeError("GitHub returned an unreadable response.")


def fetch_releases(timeout=15):
    """Return the list of releases (newest first), as GitHub returns them."""
    return _api_get(RELEASES_URL, timeout=timeout)


# --- Selection (pure) ---------------------------------------------------------

def pick_release(releases, channel):
    """Pick the release for a channel.

    stable -> newest non-prerelease, non-draft release.
    edge   -> the rolling 'edge' pre-release (CI publishes it on every main
              push); falls back to the newest pre-release.
    """
    rels = [r for r in (releases or []) if not r.get("draft")]
    if channel == "edge":
        for r in rels:
            if r.get("tag_name") == "edge":
                return r
        for r in rels:
            if r.get("prerelease"):
                return r
        return None
    # stable
    for r in rels:
        if not r.get("prerelease"):
            return r
    return None


def pick_asset(release, platform_tag):
    """Pick the installer asset matching this platform tag (e.g. 'Windows-x86_64')."""
    if not release:
        return None
    for a in release.get("assets", []):
        name = a.get("name", "")
        if platform_tag in name and not name.endswith(".sha256"):
            return a
    return None


def asset_version(asset_name):
    """Parse the version out of an asset filename, or None."""
    m = _ASSET_VERSION_RE.match(asset_name or "")
    if not m:
        return None
    try:
        return Version(m.group("ver"))
    except InvalidVersion:
        return None


def compare_versions(remote, local):
    """'newer' | 'same' | 'older' | 'unknown' for remote relative to local.

    Compares only the public/dev portion of each version, ignoring the +local
    segment (e.g. setuptools-scm's '+gHASH' / '.dYYYYMMDD' dirty suffix), so a
    clean CI build at the same commit doesn't read as a downgrade.
    """
    if remote is None or local is None:
        return "unknown"
    r, l = Version(remote.public), Version(local.public)
    if r > l:
        return "newer"
    if r < l:
        return "older"
    return "same"


# --- High-level check (needs platform/version) --------------------------------

def check_for_update(channel, releases=None):
    """Resolve what update (if any) is available on ``channel``.

    Returns a dict: release, asset, remote_version, local_version, status.
    """
    from PyReconstruct.modules.backend.updater.install_info import (
        current_version, platform_asset_tag,
    )
    if releases is None:
        releases = fetch_releases()
    release = pick_release(releases, channel)
    asset = pick_asset(release, platform_asset_tag())
    remote_v = asset_version(asset["name"]) if asset else None
    local_v = current_version()
    return {
        "release": release,
        "asset": asset,
        "remote_version": str(remote_v) if remote_v else None,
        "local_version": str(local_v) if local_v else None,
        "status": compare_versions(remote_v, local_v),
    }


# --- Download / verify / launch ----------------------------------------------

def download_asset(url, dest_path, progress_cb=None, cancel_cb=None, chunk=65536):
    """Stream ``url`` to ``dest_path``; return the sha256 hex of the bytes written.

    Calls ``progress_cb(percent)`` as it goes (when Content-Length is known) and
    aborts (raising :class:`UpdateCancelled`, deleting the partial file) if
    ``cancel_cb()`` becomes truthy.
    """
    dest_path = Path(dest_path)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            done = 0
            with open(dest_path, "wb") as fh:
                while True:
                    if cancel_cb and cancel_cb():
                        raise UpdateCancelled()
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fh.write(buf)
                    digest.update(buf)
                    done += len(buf)
                    if progress_cb and total:
                        progress_cb(int(done * 100 / total))
    except BaseException:
        try:
            dest_path.unlink()
        except OSError:
            pass
        raise
    return digest.hexdigest()


def fetch_checksum(release, asset_name):
    """Return ``(status, digest)``: ('ok', hex) | ('missing', None) | ('error', None).

    'missing' means no checksum was published for this asset (the caller may warn
    and proceed); 'error' means a checksum *was* published but could not be
    fetched or parsed (the caller should treat that as a hard failure and NOT
    install, rather than silently downgrading to "unverified").
    """
    if not release:
        return ("missing", None)
    assets = release.get("assets", [])
    # 1) a sibling "<asset>.sha256"
    for a in assets:
        if a.get("name") == asset_name + ".sha256":
            try:
                return ("ok", _download_text(a["browser_download_url"]).split()[0].strip())
            except Exception:
                return ("error", None)
    # 2) a combined SHA256SUMS manifest
    for a in assets:
        if a.get("name", "").upper() in ("SHA256SUMS", "SHA256SUMS.TXT"):
            try:
                text = _download_text(a["browser_download_url"])
            except Exception:
                return ("error", None)
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1].lstrip("*") == asset_name:
                    return ("ok", parts[0].strip())
            return ("missing", None)  # manifest present but no entry for this asset
    return ("missing", None)


def _download_text(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def launch_installer(path):
    """Open the downloaded installer with the OS so the user can complete it."""
    from PyReconstruct.modules.backend.updater.install_info import os_key
    path = str(path)
    key = os_key()
    if key == "windows":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
    elif key == "macos":
        subprocess.Popen(["open", path])
    else:
        if path.endswith(".AppImage"):
            os.chmod(path, 0o755)
            subprocess.Popen([path])
        else:
            subprocess.Popen(["xdg-open", path])

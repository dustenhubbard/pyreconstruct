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
import urllib.parse
from pathlib import Path

from packaging.version import Version, InvalidVersion

# Repo whose GitHub Releases the updater pulls installers from -- this fork, where
# its candidate builds are published. Kept as a plain literal (not imported from
# constants.gh_repo) so this module stays Qt-free / stdlib-only.
GITHUB_REPO = "dustenhubbard/PyReconstruct"

RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
USER_AGENT = "PyReconstruct-updater"

# 'PyReconstruct-<version>-<Platform>-<arch>...' -> capture <version>.
_ASSET_VERSION_RE = re.compile(r"PyReconstruct-(?P<ver>.+?)-(?:Windows|macOS|Linux)\b")

# The rolling "latest main" build is republished under this fixed GitHub tag on
# every push to main (see .github/workflows/build-installers.yml). Unlike a cut
# release, this tag is REUSED build-to-build. The Developer channel selects it by
# this tag; the Beta (prerelease) channel explicitly excludes it so the rolling
# build can never shadow a curated semver pre-release.
ROLLING_TAG = "prerelease"

# Channel values in the order their radios appear in Series > Options > Updates.
# Position is the contract between the dialog's radios and the stored value; keep
# this tuple and the radio order in all_options.py in lockstep.
UPDATE_CHANNELS = ("release", "prerelease", "developer")

# Legacy channel values from installs predating the rename (stable->release,
# edge->prerelease). No legacy value maps to the newer 'developer' channel.
_LEGACY_CHANNELS = {"stable": "release", "edge": "prerelease"}


def normalize_channel(channel):
    """Map a legacy channel value to its current equivalent (else pass through)."""
    return _LEGACY_CHANNELS.get(channel, channel)


def channel_radio_index(channel):
    """Index of the Updates radio for ``channel`` (legacy values normalized).

    Unknown/missing channels fall back to 0 (Stable), matching the default.
    """
    channel = normalize_channel(channel)
    try:
        return UPDATE_CHANNELS.index(channel)
    except ValueError:
        return 0


def radio_response_channel(radio_response):
    """Map a QuickDialog radio response to a channel value (positional).

    ``radio_response`` is the list of ``(label, checked)`` tuples QuickDialog
    returns for a radio group, one per button in UI order. Returns the channel
    for the checked button; falls back to 'release' if somehow none is checked.
    """
    for i, item in enumerate(radio_response):
        if item[1] and i < len(UPDATE_CHANNELS):
            return UPDATE_CHANNELS[i]
    return "release"


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

    release    -> newest non-prerelease, non-draft release.
    prerelease -> newest release flagged ``prerelease`` (drafts excluded),
                  EXCLUDING the rolling ``ROLLING_TAG`` build. The pipeline
                  publishes curated semver pre-releases (v1.30.0-alpha.N -> -rc
                  -> final), each flagged ``prerelease=true`` by CI, so the
                  newest such release is the current pre-release. Excluding the
                  rolling tag explicitly (rather than relying on newest-first
                  ordering) guarantees the rolling build can never shadow a
                  curated semver pre-release, even if GitHub's ordering shifts.
    developer  -> the rolling "latest main" build, selected by ``ROLLING_TAG``.
                  Its tag is reused build-to-build, so it is identified by tag,
                  not by version; freshness is decided later from the asset's
                  version (the CI-baked ``.devN`` commit distance).
    """
    channel = normalize_channel(channel)
    rels = [r for r in (releases or []) if not r.get("draft")]
    if channel == "developer":
        for r in rels:
            if r.get("tag_name") == ROLLING_TAG:
                return r
        return None
    if channel == "prerelease":
        for r in rels:
            if r.get("prerelease") and r.get("tag_name") != ROLLING_TAG:
                return r
        return None
    # release (stable)
    for r in rels:
        if not r.get("prerelease"):
            return r
    return None


def pick_asset(release, platform_tag):
    """Pick the installer asset matching this platform tag (e.g. 'Windows-x86_64').

    The substring match is unambiguous because ``platform_asset_tag`` always
    carries the OS label and the arch tokens are not substrings of each other:
    'macOS-x86_64' and 'macOS-arm64' (and 'Windows-x86_64') each match exactly
    one asset and never another arch's or OS's. If asset tags are ever shortened
    to bare 'x86_64'/'arm64', that guarantee is lost -- keep the OS-label prefix.
    """
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

# Hosts installer/checksum bytes may come from. Release-asset URLs in the GitHub
# API JSON resolve to github.com and its asset CDN (*.githubusercontent.com);
# anything else -- an http:// downgrade or an off-host redirect -- is refused
# loudly instead of followed.
_ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")


def _check_download_url(url):
    """Raise RuntimeError unless ``url`` is https on an allowlisted GitHub host."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "https":
        raise RuntimeError(f"Refusing non-https download URL: {url}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
        raise RuntimeError(f"Refusing download from unexpected host: {host or url!r}")


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to allowlisted https GitHub hosts; fail loudly otherwise."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_download(url, timeout):
    """urlopen with the scheme/host allowlist enforced on the URL and every redirect."""
    _check_download_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_AllowlistedRedirectHandler())
    return opener.open(req, timeout=timeout)


def download_asset(url, dest_path, progress_cb=None, cancel_cb=None, chunk=65536):
    """Stream ``url`` to ``dest_path``; return the sha256 hex of the bytes written.

    Calls ``progress_cb(percent)`` as it goes (when Content-Length is known) and
    aborts (raising :class:`UpdateCancelled`, deleting the partial file) if
    ``cancel_cb()`` becomes truthy.
    """
    dest_path = Path(dest_path)
    digest = hashlib.sha256()
    try:
        with _open_download(url, timeout=30) as resp:
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
    with _open_download(url, timeout=timeout) as resp:
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

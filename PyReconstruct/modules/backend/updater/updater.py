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

# A rolling "latest main" build was once republished under this fixed GitHub tag
# on every push to main. That build (and the "Developer" update channel that
# selected it) has been retired -- developers now run source installs to track
# main (see the developer-install docs in the README). The constant is KEPT
# deliberately: the Beta (prerelease) channel still excludes this tag as defense
# in depth. Old clients (v1.21.0-beta-2 and earlier) predate this exclusion and
# relied on release ordering, which a recreate-on-every-push rolling build
# defeated -- that was the field regression that prompted the removal. If a
# rolling-style release under this tag ever reappears, the exclusion guarantees a
# current client's Beta channel can never be shadowed by it.
ROLLING_TAG = "prerelease"

# Channel values in the order their radios appear in Series > Options > Updates.
# Position is the contract between the dialog's radios and the stored value; keep
# this tuple and the radio order in all_options.py in lockstep.
UPDATE_CHANNELS = ("release", "prerelease")

# Channel values that no longer exist as radios but may still be stored in an
# install's options -- remapped to a current channel so an old config opens the
# dialog on a valid radio and picks a valid release (never crashes or silently
# lands on index 0). Sources:
#   stable/edge -> the pre-rename names (stable->release, edge->prerelease).
#   developer   -> the removed Developer channel; the maintainer (at minimum) has
#                  it stored, so it must remap to Beta (prerelease), the closest
#                  surviving channel, rather than falling back to Stable.
_LEGACY_CHANNELS = {"stable": "release", "edge": "prerelease", "developer": "prerelease"}


def normalize_channel(channel):
    """Map a legacy channel value to its current equivalent (else pass through)."""
    return _LEGACY_CHANNELS.get(channel, channel)


def other_flavor_url(timeout=6):
    """The download page for the OTHER build: stable from Dev, the newest beta
    from stable.

    Resolved when clicked, never stored, so the link cannot go stale:

    * From the Dev build the answer is GitHub's own ``releases/latest``
      redirect, which always lands on the newest stable release. No API call.
    * From the stable build there is no such redirect for pre-releases, so the
      newest curated beta is looked up through the same release list the
      updater reads (drafts and the rolling tag excluded, exactly as
      ``pick_release`` does). Any failure -- offline, rate-limited, no beta
      right after a final ships -- falls back to the releases index, which
      lists everything.
    """
    base = f"https://github.com/{GITHUB_REPO}/releases"
    if pinned_channel() == "prerelease":
        return f"{base}/latest"
    try:
        rels = [r for r in (fetch_releases(timeout=timeout) or []) if not r.get("draft")]
        newest_pre = next(
            (r for r in rels
             if r.get("prerelease") and r.get("tag_name") != ROLLING_TAG),
            None,
        )
        if newest_pre and newest_pre.get("html_url"):
            return newest_pre["html_url"]
    except Exception:
        pass
    return base


def pinned_channel():
    """The update channel this build follows.

    The channel is a property of the installed build, not a per-series option:
    the stable app follows the release channel and the Dev flavor (which
    packaging marks with PYRECON_APP_NAME) follows the prerelease channel.
    The old Series Options radio let one install wander between channels,
    which is exactly what the two side-by-side builds replace.
    """
    from PyReconstruct.modules.datatypes.series_owner import app_display_name
    return "prerelease" if "Dev" in app_display_name() else "release"


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
                  EXCLUDING any release under ``ROLLING_TAG``. The pipeline
                  publishes curated semver pre-releases (v1.30.0-alpha.N -> -rc
                  -> final), each flagged ``prerelease=true`` by CI, so the
                  newest such release is the current pre-release. The rolling
                  Developer build that once used ``ROLLING_TAG`` is gone, but the
                  exclusion stays as defense in depth: excluding that tag
                  explicitly (rather than relying on newest-first ordering)
                  guarantees a rolling-style release can never shadow a curated
                  semver pre-release, even if GitHub's ordering shifts or such a
                  release reappears.

    The removed ``developer`` channel (and legacy ``stable``/``edge`` values)
    are remapped by :func:`normalize_channel` before this dispatch, so a stored
    ``developer`` option resolves to the ``prerelease`` branch here.
    """
    channel = normalize_channel(channel)
    rels = [r for r in (releases or []) if not r.get("draft")]
    newest_stable = next((r for r in rels if not r.get("prerelease")), None)
    if channel == "prerelease":
        newest_pre = next(
            (r for r in rels
             if r.get("prerelease") and r.get("tag_name") != ROLLING_TAG),
            None,
        )
        return _newer_of(newest_pre, newest_stable)
    # release (stable)
    return newest_stable


def _tag_version(release):
    """The release's tag parsed as a version, or None if it is not one.

    Tags in this project are `vX.Y.Z` and `vX.Y.Z-beta-N` / `-alpha.N` / `rcN`,
    all of which `packaging` parses once the leading `v` is dropped. A tag that
    is not a version at all (the retired rolling `prerelease` tag, or anything
    hand-made) yields None, and the caller treats that as "cannot compare"
    rather than as "older".
    """
    if not release:
        return None
    tag = (release.get("tag_name") or "").lstrip("vV")
    try:
        return Version(tag)
    except InvalidVersion:
        return None


def _newer_of(pre, stable):
    """The newer of a pre-release and a stable release, preferring `pre` on ties.

    This is what makes the Beta channel a SUPERSET of Stable rather than a set
    disjoint from it. A tester on Beta wants the newest thing that exists; when
    a stable release is the newest thing, withholding it strands them.

    That is not hypothetical. v1.21.0 shipped as a stable cut from a release
    branch, its superseded betas were retired at publish, and every Beta-channel
    user was then offered NOTHING: `pick_release` returned None, so there was no
    prompt and no error either. The bug is invisible from the inside, which is why
    it wants a test rather than a comment.

    Ties go to the pre-release deliberately. When a pre-release and a stable
    release carry the same version, the pre-release is the one with the narrower
    audience, and a Beta user asked for that audience.
    """
    if pre is None:
        return stable
    if stable is None:
        return pre
    pv, sv = _tag_version(pre), _tag_version(stable)
    if pv is None or sv is None:
        return pre
    return stable if sv > pv else pre


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

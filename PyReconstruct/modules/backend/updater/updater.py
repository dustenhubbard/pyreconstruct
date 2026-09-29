"""GitHub-Releases-based updater for frozen builds.

The frozen app can't ``pip install`` or use git, so "update" means: query the
GitHub Releases API, pick the installer asset for this platform/channel,
download it (with progress), verify its SHA-256 against the release's signed
``SHA256SUMS`` (or its ``.sha256`` file when no signature is published), then
launch the installer and quit. The dev/source update path stays in ``cli.py``.

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
# deliberately: the Nightly (prerelease) channel still excludes this tag as
# defense in depth. Old clients (v1.21.0-beta-2 and earlier) predate this
# exclusion and relied on release ordering, which a recreate-on-every-push
# rolling build defeated -- that was the field regression that prompted the
# removal. If a rolling-style release under this tag ever reappears, the
# exclusion guarantees a current client's Nightly channel can never be shadowed
# by it.
ROLLING_TAG = "prerelease"

# The flavor marker the packaging scripts put on every Dev-build asset, right
# after the platform tag: 'PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg',
# '...-Windows-x86_64-Dev-Setup.exe', '...-Linux-installer-Dev.tar.gz'. The
# updater keys the two feeds apart on it (see ``pick_asset``), so the stable app
# never downloads a Dev installer and the Dev app never downloads a stable one.
# Case-sensitive on purpose: the PEP 440 '.devYYYYMMDD' segment in a nightly's
# version sits BEFORE the platform tag and is lowercase.
DEV_ASSET_MARKER = "-Dev"
_DEV_MARKER_RE = re.compile(r"-Dev(?=[-.]|$)")

# The installer each OS label takes, as the packaging scripts name it:
# '...-Windows-x86_64[-Dev]-Setup.exe', '...-macOS-<arch>[-Dev].dmg',
# '...-Linux-installer[-Dev].tar.gz'. ``pick_asset`` accepts nothing else, so a
# release can carry other files (update archives, manifests, checksum lists)
# without any of them being offered as the installer.
_INSTALLER_SUFFIX_RE = {
    "Windows": re.compile(r"-Setup\.exe$"),
    "macOS": re.compile(r"\.dmg$"),
    "Linux": re.compile(r"-installer.*\.tar\.gz$"),
}

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
#                  it stored, so it must remap to Nightly (prerelease), the
#                  closest surviving channel, rather than falling back to Stable.
_LEGACY_CHANNELS = {"stable": "release", "edge": "prerelease", "developer": "prerelease"}

# What the user sees when a channel is named on screen. The stored values stay
# "release"/"prerelease" (they are the contract with saved options and with the
# GitHub flag they select on); only the wording is Stable/Nightly.
_CHANNEL_DISPLAY_NAMES = {"release": "Stable", "prerelease": "Nightly"}


def normalize_channel(channel):
    """Map a legacy channel value to its current equivalent (else pass through)."""
    return _LEGACY_CHANNELS.get(channel, channel)


def channel_display_name(channel):
    """'Stable' or 'Nightly': the user-facing name for a channel value.

    Accepts the legacy values too (via :func:`normalize_channel`). Anything
    unrecognized falls back to Stable rather than leaking a raw internal string
    such as ``prerelease`` into a dialog.
    """
    return _CHANNEL_DISPLAY_NAMES.get(normalize_channel(channel), "Stable")


def other_flavor_url(timeout=6):
    """The download page for the OTHER build: stable from Dev, the newest
    nightly from stable.

    Resolved when clicked, never stored, so the link cannot go stale:

    * From the Dev build the answer is GitHub's own ``releases/latest``
      redirect, which always lands on the newest stable release. No API call.
    * From the stable build there is no such redirect for pre-releases, so the
      newest nightly is looked up through the same release list the updater
      reads (drafts and the rolling tag excluded, exactly as ``pick_release``
      does). Any failure -- offline, rate-limited, no nightly published yet --
      falls back to the releases index, which lists everything.
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
    """Pick the release for a channel. Strict: nothing crosses channels.

    release    -> newest non-prerelease, non-draft release. Never a pre-release.
    prerelease -> newest release flagged ``prerelease`` (drafts excluded),
                  EXCLUDING any release under ``ROLLING_TAG``. Never a stable
                  release, even when the stable one is newer: the Dev app is the
                  only build on this channel, and a stable installer offered to
                  it installs a second app beside it instead of updating it.
                  When no nightly is published, the answer is None and the
                  caller reads that as "no update", not as an error.

    The nightly pipeline publishes PEP 440 dev versions
    (``v1.24.0.dev20260928``), each flagged ``prerelease=true`` by CI, so the
    newest such release is the current nightly. Older test builds were
    ``vX.Y.Z-beta-N``; they parse the same way and sort below any dev version
    of the next release. The rolling Developer build that once used
    ``ROLLING_TAG`` is gone, but the exclusion stays as defense in depth:
    excluding that tag explicitly (rather than relying on newest-first
    ordering) guarantees a rolling-style release can never shadow a nightly,
    even if GitHub's ordering shifts or such a release reappears.

    The removed ``developer`` channel (and legacy ``stable``/``edge`` values)
    are remapped by :func:`normalize_channel` before this dispatch, so a stored
    ``developer`` option resolves to the ``prerelease`` branch here.
    """
    channel = normalize_channel(channel)
    rels = [r for r in (releases or []) if not r.get("draft")]
    if channel == "prerelease":
        return next(
            (r for r in rels
             if r.get("prerelease") and r.get("tag_name") != ROLLING_TAG),
            None,
        )
    # release (stable)
    return next((r for r in rels if not r.get("prerelease")), None)


def _tag_version(release):
    """The release's tag parsed as a version, or None if it is not one.

    Tags in this project are `vX.Y.Z` for stable releases and
    `vX.Y.Z.devYYYYMMDD` for nightlies (older test builds were `vX.Y.Z-beta-N`
    / `-alpha.N` / `rcN`), all of which `packaging` parses once the leading `v`
    is dropped. A tag that is not a version at all (the retired rolling
    `prerelease` tag, or anything hand-made) yields None, and the caller
    treats that as "cannot compare" rather than as "older".
    """
    if not release:
        return None
    tag = (release.get("tag_name") or "").lstrip("vV")
    try:
        return Version(tag)
    except InvalidVersion:
        return None


def is_dev_asset(asset_name):
    """True when an asset name carries the Dev flavor marker (``-Dev``).

    The marker follows the platform tag and is itself followed by a separator
    or the end of the name, so ``...-macOS-arm64-Dev.dmg`` and
    ``...-Windows-x86_64-Dev-Setup.exe`` are Dev assets while a hypothetical
    ``...-Development.exe`` is not.
    """
    return bool(_DEV_MARKER_RE.search(asset_name or ""))


def pick_asset(release, platform_tag, dev=False):
    """Pick the installer asset for this platform tag AND this build flavor.

    ``platform_tag`` is e.g. 'Windows-x86_64' (see ``platform_asset_tag``).
    ``dev`` says which flavor is asking: the Dev app (``dev=True``) accepts only
    assets carrying the ``-Dev`` marker, the stable app (``dev=False``) accepts
    only assets without it. A release that has no asset for this platform and
    flavor yields None, which callers read as "no update available", never as
    an error: an installer for the OTHER flavor would install a second app
    beside this one rather than update it, so it must not be offered.

    The platform substring match is unambiguous because ``platform_asset_tag``
    always carries the OS label and the arch tokens are not substrings of each
    other: 'macOS-x86_64' and 'macOS-arm64' (and 'Windows-x86_64') each match
    exactly one asset and never another arch's or OS's. If asset tags are ever
    shortened to bare 'x86_64'/'arm64', that guarantee is lost -- keep the
    OS-label prefix.

    Only the installer for the tag's OS label counts (``is_installer_asset``):
    ``-Setup.exe`` on Windows, ``.dmg`` on macOS, ``-installer*.tar.gz`` on
    Linux. Any other file on the release is never picked, whatever its name
    contains.
    """
    if not release:
        return None
    for a in release.get("assets", []):
        name = a.get("name", "")
        if platform_tag not in name or name.endswith(".sha256"):
            continue
        if not is_installer_asset(name, platform_tag):
            continue
        if is_dev_asset(name) != bool(dev):
            continue
        return a
    return None


def is_installer_asset(asset_name, platform_tag):
    """True when ``asset_name`` is an installer for the OS in ``platform_tag``.

    The OS label is the part of the tag before the first '-' ('Windows',
    'macOS', 'Linux'); an unknown label has no installer.
    """
    pattern = _INSTALLER_SUFFIX_RE.get((platform_tag or "").split("-", 1)[0])
    return bool(pattern and pattern.search(asset_name or ""))


def asset_version(asset_name):
    """Parse the version out of an asset filename, or None.

    The version is everything between 'PyReconstruct-' and the platform tag, so
    'PyReconstruct-1.24.0.dev20260928-macOS-arm64-Dev.dmg' yields
    ``1.24.0.dev20260928`` and the ``-Dev`` marker after the tag is ignored.
    """
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

    Strict per-channel feed. The channel picks the release (stable or nightly,
    see ``pick_release``) and also the asset flavor: the Dev app is the only
    build pinned to the prerelease channel (``pinned_channel``), so the
    prerelease channel takes ``-Dev`` assets and the release channel takes the
    plain ones (``pick_asset``). With no matching release or asset the result
    carries ``asset=None`` and ``status="unknown"``, and callers treat that as
    "nothing to offer".
    """
    from PyReconstruct.modules.backend.updater.install_info import (
        current_version, platform_asset_tag,
    )
    if releases is None:
        releases = fetch_releases()
    channel = normalize_channel(channel)
    release = pick_release(releases, channel)
    asset = pick_asset(release, platform_asset_tag(), dev=(channel == "prerelease"))
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


# The signed checksum list each release carries, and its minisign signature.
# The release job writes SHA256SUMS (every asset but the .sha256 files and
# itself, in sha256sum's format) and signs it with the key whose public half is
# in ``signing_keys``. Its trusted comment names the tag, so the list from one
# release cannot be passed off as another's.
SUMS_ASSET = "SHA256SUMS"
SIGNATURE_ASSET = "SHA256SUMS.minisig"

# Both files are a few kilobytes; anything much bigger is not ours.
_MAX_SIGNED_BYTES = 1 << 20

_SUMS_LINE_RE = re.compile(r"([0-9a-fA-F]{64}) [ *](.+)")


def _download_bytes(url, limit=_MAX_SIGNED_BYTES, timeout=15):
    """The exact bytes at ``url``; raise RuntimeError past ``limit``.

    Exact bytes, not text, because a signature covers the bytes as published.
    """
    with _open_download(url, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"Refusing an oversized download: {url}")
    return data


def parse_sums(data):
    """``{name: sha256}`` from a sha256sum-format list.

    Lines that do not parse are skipped. A name listed twice with different
    hashes is dropped, so it reads as not listed rather than as either hash.
    """
    sums, conflicts = {}, set()
    for line in data.decode("utf-8", "replace").splitlines():
        m = _SUMS_LINE_RE.fullmatch(line.rstrip("\r"))
        if not m:
            continue
        digest, name = m.group(1).lower(), m.group(2)
        if sums.get(name, digest) != digest:
            conflicts.add(name)
        sums[name] = digest
    for name in conflicts:
        del sums[name]
    return sums


def trusted_comment_fields(comment):
    """``{key: value}`` from a trusted comment such as ``tag:v1.24.0 file:SHA256SUMS``."""
    fields = {}
    for token in (comment or "").split():
        key, sep, value = token.partition(":")
        if sep:
            fields[key] = value
    return fields


def fetch_signed_checksum(release, asset_name, trusted_keys=None):
    """Return ``(status, digest)`` for ``asset_name`` from the signed SHA256SUMS.

    * ``('absent', None)``: the release publishes no signature, so the caller
      falls back to :func:`fetch_checksum` (releases from before signing, or
      one built without the signing key).
    * ``('ok', hex)``: the signature is valid, made by a compiled-in key, names
      this release's tag, and SHA256SUMS lists the asset.
    * ``('bad_signature', None)``: a signature is published but is invalid,
      malformed, by an unknown key, names another tag, or has no SHA256SUMS
      beside it. Refuse the update.
    * ``('unlisted', None)``: the signature is valid but SHA256SUMS does not
      list the asset. Refuse the update.
    * ``('error', None)``: either file was published but could not be fetched.
      Refuse, and let the user try again.
    """
    from PyReconstruct.modules.backend.updater import minisign
    from PyReconstruct.modules.backend.updater.signing_keys import TRUSTED_KEYS

    if trusted_keys is None:
        trusted_keys = TRUSTED_KEYS
    assets = {a.get("name"): a for a in (release or {}).get("assets") or []
              if isinstance(a, dict)}
    sig_asset = assets.get(SIGNATURE_ASSET)
    if sig_asset is None:
        return ("absent", None)
    sums_asset = assets.get(SUMS_ASSET)
    if sums_asset is None:
        return ("bad_signature", None)
    try:
        signature = _download_bytes(sig_asset["browser_download_url"])
        sums = _download_bytes(sums_asset["browser_download_url"])
    except Exception:
        return ("error", None)
    try:
        comment = minisign.verify(sums, signature, trusted_keys)
    except minisign.SignatureError:
        return ("bad_signature", None)
    fields = trusted_comment_fields(comment)
    tag = (release or {}).get("tag_name")
    if not tag or fields.get("tag") != tag or fields.get("file") != SUMS_ASSET:
        return ("bad_signature", None)
    digest = parse_sums(sums).get(asset_name)
    if digest is None:
        return ("unlisted", None)
    return ("ok", digest)


def verified_checksum(release, asset_name):
    """The checksum the installer must match: signed if published, else per file.

    Returns :func:`fetch_signed_checksum`'s statuses, except that a release
    with no signature goes through :func:`fetch_checksum` and returns one of
    its statuses ('ok', 'missing', 'error') instead of 'absent'.
    """
    status, digest = fetch_signed_checksum(release, asset_name)
    if status == "absent":
        return fetch_checksum(release, asset_name)
    return (status, digest)


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

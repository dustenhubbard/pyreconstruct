"""Atomic file-replace with a short retry for transient Windows locks (Qt-free).

``os.replace`` over a destination fails intermittently on Windows when
antivirus, the Search indexer, or a sync client (OneDrive/Dropbox) briefly holds
a handle on the file -- surfacing as WinError 5 (access denied), 32 (sharing
violation), or 33 (lock violation). These locks clear in well under a second, so
a few retries with backoff turn a spurious "save failed" into a successful save.

This bit users on background section saves (a save fires on mouse-wheel scroll /
section switch), where a transient lock produced a scary error even though the
data was safe. Genuine errors -- e.g. the destination directory is gone
(ENOENT) -- are NOT retried and propagate immediately; and after the final
attempt the last error propagates unchanged, so a real failure still surfaces.
"""
import os
import time
import errno

# Windows transient-lock codes worth retrying.
_RETRIABLE_WINERROR = frozenset({5, 32, 33})
# POSIX errnos that can be transient on networked / synced filesystems.
_RETRIABLE_ERRNO = frozenset({errno.EACCES, errno.EPERM})


def _is_retriable(exc: OSError) -> bool:
    """Whether ``exc`` is a transient lock worth retrying (vs. a real failure)."""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:            # Windows: the winerror code is authoritative
        return winerror in _RETRIABLE_WINERROR
    return getattr(exc, "errno", None) in _RETRIABLE_ERRNO


def replace_with_retry(src, dst, attempts: int = 5, base_delay: float = 0.1,
                       _sleep=time.sleep) -> None:
    """``os.replace(src, dst)``, retrying transient locks with exponential backoff.

    Non-retriable errors raise immediately; after the final attempt the last
    error propagates unchanged. Worst-case added latency is ~1.5 s
    (0.1+0.2+0.4+0.8) and only on a genuinely contended replace.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if attempt == attempts - 1 or not _is_retriable(e):
                raise
            _sleep(base_delay * (2 ** attempt))

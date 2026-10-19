"""Whether a folder is on a network file system.

SQLite's locks do not hold on a network share, so a database there can be
damaged by two machines at once. The local store (hybrid_store.py) is not used
from a folder this module calls remote; the series opens from its .jser
instead.

Each platform is read its own way:

  * macOS: statfs, by file system name (smbfs, afpfs, nfs, webdav), or any
    mount the system does not mark local;
  * Windows: a UNC path, or a drive GetDriveTypeW calls DRIVE_REMOTE (a
    mapped network drive);
  * Linux: statfs, by the file system's magic number (nfs, cifs, smb, smb2,
    9p, afs), and FUSE mounts by their name (fuse.sshfs).

A folder that does not exist yet is judged by the nearest folder above it
that does. When the platform call itself is missing or fails, the answer is
None (local): the default store folder is local on every platform, and the
Linux check in hybrid_store.py still runs.
"""

import ctypes
import ctypes.util
import ntpath
import os
import platform as _platform
import sys
from typing import Optional

## macOS f_fstypename values of a network mount
MACOS_NETWORK = {"smbfs", "afpfs", "nfs", "webdav"}
## macOS f_flags bit of a mount the system calls local (<sys/mount.h>)
MNT_LOCAL = 0x00001000

## Linux statfs f_type of a network file system (<linux/magic.h>, cifs and smb2
## from fs/smb/client)
LINUX_NETWORK_MAGIC = {
    0x6969: "nfs",
    0xFF534D42: "cifs",
    0x517B: "smb",
    0xFE534D42: "smb2",
    0x01021997: "9p",
    0x5346414F: "afs",
    0x6B414653: "afs",
}
LINUX_FUSE_MAGIC = 0x65735546
## FUSE file systems that reach another machine, by their mountinfo name
LINUX_NETWORK_FUSE = {"fuse.sshfs"}

## GetDriveTypeW
DRIVE_REMOTE = 4


def networkFileSystem(path : str, platform : Optional[str] = None):
    """The network file system path is on, as a short name, or None if local.

        Params:
            path (str): a folder or file, existing or not
            platform (str): sys.platform, for tests
    """
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return windowsRemote(path)
    path = _existing(path)
    if platform == "darwin":
        return macosRemote(path)
    if platform.startswith("linux"):
        return linuxRemote(path)
    return None


def _existing(path : str) -> str:
    """path, or the nearest folder above it that exists."""
    path = os.path.abspath(path)
    while not os.path.exists(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


## macOS ----------------------------------------------------------------------

class _MacStatfs(ctypes.Structure):
    """struct statfs with 64-bit inodes (<sys/mount.h>)."""
    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", ctypes.c_int32 * 2),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * 16),
        ("f_mntonname", ctypes.c_char * 1024),
        ("f_mntfromname", ctypes.c_char * 1024),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def _macStatfs(path : str):
    """(file system name, flags) of the mount holding path, or None."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        # Intel builds name the 64-bit-inode call apart; on arm64 it is the only one
        name = "statfs" if _platform.machine() == "arm64" else "statfs$INODE64"
        statfs = libc[name]
    except (OSError, AttributeError, TypeError):
        return None
    buf = _MacStatfs()
    if statfs(os.fsencode(path), ctypes.byref(buf)) != 0:
        return None
    return buf.f_fstypename.decode("ascii", "replace"), buf.f_flags


def macosRemote(path : str, statfs=_macStatfs):
    """The network file system of path on macOS, or None."""
    found = statfs(path)
    if found is None:
        return None
    name, flags = found
    if name in MACOS_NETWORK:
        return name
    if not flags & MNT_LOCAL:
        return f"{name}, not local"
    return None


## Linux ----------------------------------------------------------------------

def _linuxStatfs(path : str):
    """The f_type of the file system holding path, or None."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        statfs = libc.statfs
    except (OSError, AttributeError, TypeError):
        return None
    # struct statfs opens with f_type, a C long; the rest is not read
    buf = ctypes.create_string_buffer(512)
    if statfs(os.fsencode(path), buf) != 0:
        return None
    return ctypes.c_long.from_buffer(buf).value & 0xFFFFFFFF


def _linuxMountType(path : str):
    """The mountinfo type name of the mount holding path (fuse.sshfs, ...), or None."""
    from .hybrid_store import fsType
    return fsType(path)


def linuxRemote(path : str, statfs=_linuxStatfs, mount_type=_linuxMountType):
    """The network file system of path on Linux, or None."""
    magic = statfs(path)
    if magic is None:
        return None
    if magic in LINUX_NETWORK_MAGIC:
        return LINUX_NETWORK_MAGIC[magic]
    if magic == LINUX_FUSE_MAGIC:
        name = mount_type(path)
        if name in LINUX_NETWORK_FUSE:
            return name
    return None


## Windows --------------------------------------------------------------------

def _windowsDriveType(root : str):
    """GetDriveTypeW of a drive root such as "Z:\\", or None."""
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(root)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def windowsRemote(path : str, drive_type=_windowsDriveType):
    """The network location of path on Windows, or None."""
    path = ntpath.abspath(path)
    upper = path.upper()
    if upper.startswith("\\\\?\\UNC\\"):
        return "UNC path"
    if upper.startswith("\\\\?\\") or upper.startswith("\\\\.\\"):
        path = path[4:]
    elif path.startswith("\\\\"):
        return "UNC path"
    drive = ntpath.splitdrive(path)[0]
    if not drive or drive.startswith("\\\\"):
        return "UNC path" if drive else None
    if drive_type(drive + "\\") == DRIVE_REMOTE:
        return "network drive"
    return None

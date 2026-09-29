"""The Linux host-library filter in packaging/PyReconstruct.spec.

The spec drops every bundled library whose name matches `_HOST_LIBS`, so the
host's copy loads instead. A name that matches by mistake leaves the app without
a library it needs on a desktop that lacks it; a name that should match but
does not leaves an old copy that shadows the host's. The pattern is read out of
the spec itself, so this checks what the build runs.
"""

import ast
import re
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "packaging" / "PyReconstruct.spec"


def _host_libs():
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "_HOST_LIBS" for t in node.targets)
        ):
            return re.compile(node.value.args[0].value)
    raise AssertionError("_HOST_LIBS not found in the spec")


HOST_LIBS = _host_libs()


@pytest.mark.parametrize("name", [
    # the desktop's base libraries
    "libstdc++.so.6", "libgcc_s.so.1", "libglib-2.0.so.0", "libgio-2.0.so.0",
    "libdbus-1.so.3", "libselinux.so.1", "libgpg-error.so.0", "libp11-kit.so.0",
    # linked by nothing left in the bundle, only by the libraries above
    "libgnutls.so.30", "libnettle.so.6", "libhogweed.so.4", "libgmp.so.10",
    "libtasn1.so.6", "libidn2.so.0", "libunistring.so.2",
    "libsystemd.so.0", "libgcrypt.so.20", "libcap.so.2", "liblz4.so.1",
    "libpcre.so.1", "libpcre2-8.so.0",
])
def test_left_to_the_host(name):
    assert HOST_LIBS.match(name)


@pytest.mark.parametrize("name", [
    # what Qt's xcb plugin needs and a desktop may not have
    "libxkbcommon-x11.so.0", "libxcb-cursor.so.0", "libatomic.so.1",
    # linked by bundled code: Python's own extension modules, Qt, the app
    "liblzma.so.5", "libffi.so.6", "libbz2.so.1", "libzstd.so.1",
    "libssl.so.1.1", "libcrypto.so.1.1", "libsqlite3.so.0",
    "libpython3.11.so.1.0", "libQt6Core.so.6",
    # a longer name that only starts like one on the list
    "libcap-ng.so.0", "libgmpxx.so.4",
    # vendored into a wheel by auditwheel, hash suffixed
    "libgnutls-1a2b3c4d.so.30", "libz-1a2b3c4d.so.1",
])
def test_stays_bundled(name):
    assert not HOST_LIBS.match(name)

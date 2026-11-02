"""Saving a series preserves existing POSIX permissions and honors umask."""

import os
import stat
from pathlib import Path
from contextlib import contextmanager

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import fast_loads
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.series import _atomicWrite

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")


@contextmanager
def umask(mask):
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def series(shapes1_jser):
    series = Series.openJser(str(shapes1_jser), progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    yield series
    series.leave_open = False
    series.close()


@pytest.mark.parametrize("mode", [0o600, 0o660], ids=["private", "group-writable"])
@pytest.mark.parametrize("backup", [False, True], ids=["own-file", "backup"])
def test_saving_an_existing_jser_preserves_permissions(series, tmp_path, mode, backup):
    target = tmp_path / "backup.jser" if backup else Path(series.jser_fp)
    if backup:
        target.write_bytes(b"previous backup")
    target.chmod(mode)
    series.current_section = max(series.sections)

    with umask(0o022):
        series.saveJser(str(target) if backup else None)

    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert fast_loads(target.read_bytes())["series"]["current_section"] == max(series.sections)


@pytest.mark.parametrize("mask, expected", [(0o022, 0o644), (0o077, 0o600), (0o002, 0o664)])
def test_saving_a_new_jser_respects_umask(series, tmp_path, mask, expected):
    target = tmp_path / "new.jser"
    os.chmod(series.jser_fp, 0o600)

    with umask(mask):
        series.saveJser(str(target))

    assert stat.S_IMODE(target.stat().st_mode) == expected
    assert fast_loads(target.read_bytes())["series"]["current_section"] == series.current_section


def test_private_permissions_apply_before_streaming(tmp_path):
    target = tmp_path / "private.jser"
    target.write_bytes(b"old")
    target.chmod(0o600)
    observed_modes = []

    def write(f):
        observed_modes.append(stat.S_IMODE(os.fstat(f.fileno()).st_mode))
        f.write(b"new")

    with umask(0o022):
        _atomicWrite(str(target), write)

    assert observed_modes == [0o600]
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("streaming", [False, True], ids=["bytes", "stream"])
def test_permission_copy_failure_keeps_the_old_file(tmp_path, monkeypatch, streaming):
    target = tmp_path / "private.jser"
    target.write_bytes(b"old")
    target.chmod(0o600)

    def denied(path, mode):
        raise PermissionError("Cannot preserve permissions")

    monkeypatch.setattr(os, "chmod", denied)
    data = (lambda f: f.write(b"new")) if streaming else b"new"
    with pytest.raises(PermissionError, match="Cannot preserve permissions"):
        _atomicWrite(str(target), data)

    assert target.read_bytes() == b"old"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["private.jser"]

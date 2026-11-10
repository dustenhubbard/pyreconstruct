"""Windows save cleanup, with read-only deletion modeled on other platforms."""

import os
import stat

import pytest

from PyReconstruct.modules.backend.func import atomic_io
from PyReconstruct.modules.datatypes import series as series_module


class WindowsReadOnlyRemoval:
    name = "nt"

    def __getattr__(self, name):
        return getattr(os, name)

    def remove(self, path):
        if not os.stat(path).st_mode & stat.S_IWRITE:
            raise PermissionError("Windows cannot delete a read-only file")
        return os.remove(path)


@pytest.fixture
def windows_os(monkeypatch):
    if os.name != "nt":
        monkeypatch.setattr(series_module, "os", WindowsReadOnlyRemoval())


@pytest.fixture
def readonly_target(tmp_path):
    target = tmp_path / "readonly.jser"
    target.write_bytes(b"old")
    target.chmod(stat.S_IREAD)
    try:
        yield target
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("streaming", [False, True], ids=["replace-error", "stream-error"])
def test_windows_failed_save_removes_temp(
    windows_os, readonly_target, monkeypatch, streaming,
):
    def failed_replace(*args, **kwargs):
        raise PermissionError("Replacement failed")

    def failed_stream(f):
        f.write(b"partial new data")
        raise RuntimeError("Streaming failed")

    monkeypatch.setattr(atomic_io, "replace_with_retry", failed_replace)
    expected = RuntimeError if streaming else PermissionError
    message = "Streaming failed" if streaming else "Replacement failed"
    with pytest.raises(expected, match=message):
        series_module._atomicWrite(
            str(readonly_target), failed_stream if streaming else b"new data",
        )

    assert readonly_target.read_bytes() == b"old"
    assert not readonly_target.stat().st_mode & stat.S_IWRITE
    assert sorted(p.name for p in readonly_target.parent.iterdir()) == ["readonly.jser"]


@pytest.mark.parametrize("streaming", [False, True], ids=["bytes", "stream"])
def test_windows_writable_destination_is_replaced(windows_os, tmp_path, streaming):
    target = tmp_path / "writable.jser"
    target.write_bytes(b"old")
    data = (lambda f: f.write(b"new")) if streaming else b"new"

    series_module._atomicWrite(str(target), data)

    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & stat.S_IWRITE
    assert sorted(p.name for p in tmp_path.iterdir()) == ["writable.jser"]


@pytest.mark.skipif(os.name != "nt", reason="Native Windows read-only replacement")
@pytest.mark.parametrize("streaming", [False, True], ids=["bytes", "stream"])
def test_windows_readonly_destination_is_not_replaced(readonly_target, monkeypatch, streaming):
    # Exercise Windows replacement without the transient-lock retry delay.
    monkeypatch.setattr(atomic_io, "replace_with_retry", os.replace)
    data = (lambda f: f.write(b"new")) if streaming else b"new"

    with pytest.raises(PermissionError):
        series_module._atomicWrite(str(readonly_target), data)

    assert readonly_target.read_bytes() == b"old"
    assert not readonly_target.stat().st_mode & stat.S_IWRITE
    assert sorted(p.name for p in readonly_target.parent.iterdir()) == ["readonly.jser"]

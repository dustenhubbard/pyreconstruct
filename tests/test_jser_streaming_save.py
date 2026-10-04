"""The .jser is written one section at a time, and the bytes have not changed.

``Series.saveJser`` used to read every section's working file into one document,
turn the whole document into one block of bytes with ``dumps_jser``, and only
then write it. It now streams the document through ``write_jser`` (fork #437).

These tests hold the promise that made the change safe to take: the file is
byte for byte what the old path wrote. ``old_path_bytes`` below is the old
assembly, kept here as the reference, and ``dumps_jser`` is still the encoder it
calls. The comparison runs on every checked-in series fixture, in both the
minified and the pretty form, and on synthetic documents that hit the places
where streaming could drift: gaps in the numbering, non-ASCII text, non-string
keys, and a value orjson refuses, which sends the whole document through the
stdlib with different separators.

The other half is atomicity: a section that cannot be read partway through the
stream fails the save, removes the temp file, and leaves the old .jser as it was.
"""

import errno
import filecmp
import glob
import io
import json
import os
import random
import shutil
import tracemalloc

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import (
    canon_keys_inplace,
    dumps_jser,
    fast_loads,
    write_jser,
    SERIES_KEYS,
)
from PyReconstruct.modules.constants import fast_json
from PyReconstruct.modules.constants.jser_format import PRETTY_ENV_VAR
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_mod
from PyReconstruct.modules.datatypes.series import SeriesSaveError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, "dev", "assets", "checker", "files")
FIXTURES = [
    os.path.join(CHECKER, "class_series.jser"),
    os.path.join(CHECKER, "shapes1.jser"),
    os.path.join(CHECKER, "shapes2.jser"),
    os.path.join(ROOT, "tests", "fixtures", "parity_series.jser"),
]


def temp_files(jser_fp):
    """Every temp file a write of `jser_fp` could have left in its folder.

    ``.save-<hex>.tmp`` is what ``_atomicWrite`` makes now; ``<jser>.tmp*`` is
    checked too, so a return to a name built from the series name shows up.
    """
    folder = glob.escape(os.path.dirname(jser_fp))
    return (
        glob.glob(os.path.join(folder, ".save-*.tmp"))
        + glob.glob(glob.escape(jser_fp) + ".tmp*")
    )


def reopen_at(fp):
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


def open_copy(tmp_path, source):
    if not os.path.exists(source):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {source}")
    fp = str(tmp_path / os.path.basename(source))
    shutil.copyfile(source, fp)
    return reopen_at(fp)


def old_path_bytes(series):
    """What ``saveJser`` wrote before #437: the whole document, then dumps_jser."""
    snums = sorted(series.sections)
    jser_data = {
        "sections": [None] * (snums[-1] + 1),
        "series": {},
        "log": "",
    }
    for snum in snums:
        fp = os.path.join(series.hidden_dir, series.sections[snum])
        with open(fp, "rb") as f:
            jser_data["sections"][snum] = fast_loads(f.read())
    with open(series.filepath, "rb") as f:
        filedata = fast_loads(f.read())
    filedata.pop("log_set", None)
    log_set_str = str(series.log_set)
    if log_set_str:
        jser_data["log"] += "\n" + log_set_str
    jser_data["series"] = filedata
    existing_log_fp = os.path.join(series.hidden_dir, "existing_log.csv")
    if os.path.isfile(existing_log_fp):
        with open(existing_log_fp, "r", encoding="utf-8", errors="replace") as f:
            existing_log = "".join(line for line in f.readlines() if line.strip())
        jser_data["log"] = existing_log + jser_data["log"]
    canon_keys_inplace(jser_data["series"], SERIES_KEYS)
    return dumps_jser(jser_data)


def streamed(doc, pretty=None):
    """``write_jser`` into memory, from a document already built."""
    buf = io.BytesIO()
    rest = {k: v for k, v in doc.items() if k != "sections"}
    write_jser(buf, lambda: iter(doc["sections"]), lambda: rest, pretty=pretty)
    return buf.getvalue()


@pytest.fixture(params=[False, True], ids=["orjson", "stdlib-only"])
def orjson_state(request):
    saved = fast_json._HAVE_ORJSON
    fast_json._HAVE_ORJSON = saved and not request.param
    yield
    fast_json._HAVE_ORJSON = saved


# --------------------------------------------------------------------------
# the real save, on every fixture
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pretty", ["", "1"], ids=["minified", "pretty"])
@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_the_streamed_save_matches_the_old_path(tmp_path, monkeypatch, source, pretty):
    monkeypatch.setenv(PRETTY_ENV_VAR, pretty)
    series = open_copy(tmp_path, source)
    try:
        # the session log carries an entry, so the "log" member is not empty
        series.addLog(None, None, "Streaming save test")
        series.save()
        reference = tmp_path / "reference.jser"
        reference.write_bytes(old_path_bytes(series))

        series.saveJser()

        assert filecmp.cmp(series.jser_fp, reference, shallow=False)
        assert temp_files(series.jser_fp) == []
    finally:
        series.close()


def test_two_streamed_saves_are_byte_identical(tmp_path):
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        first = open(series.jser_fp, "rb").read()
        series.saveJser()
        assert open(series.jser_fp, "rb").read() == first
    finally:
        series.close()


# --------------------------------------------------------------------------
# write_jser against dumps_jser, on the documents streaming could get wrong
# --------------------------------------------------------------------------

def _doc(**extra_series):
    series = {"current_section": 1, "src_dir": "", "editors": ["b", "a"]}
    series.update(extra_series)
    return {
        "sections": [
            None,
            {"src": "a.tif", "mag": 0.00254, "contours": {"d01": [[[1.5], [2.5], [0, 0, 0], True, False, False, "none", []]]}},
            None,
            {"src": "c.tif", "contours": {}, "flags": [], "tforms": {"default": [1, 0, 0, 0, 1, 0]}},
        ],
        "series": series,
        "log": "Date,Time\n2026-10-03,12:00",
    }


@pytest.mark.parametrize("pretty", [False, True], ids=["minified", "pretty"])
@pytest.mark.parametrize("doc", [
    _doc(),
    _doc(comment="café \U0001F600 中"),
    _doc(obj_attrs={1: "int key", "x": {2.5: "float key"}}),
    # past 64 bits: orjson raises, so the whole document goes to the stdlib
    _doc(huge=2 ** 70),
    {"sections": [], "series": {}, "log": ""},
    {"sections": [None], "series": {}, "log": "", "extra": [1, 2]},
], ids=["plain", "non-ascii", "non-str-keys", "orjson-refuses", "empty", "extra-member"])
def test_write_jser_matches_dumps_jser(doc, pretty, orjson_state):
    assert streamed(doc, pretty) == dumps_jser(doc, pretty)


def test_a_value_orjson_refuses_late_rewrites_every_part_with_stdlib_separators():
    """The fallback decides for the whole file, so earlier parts must change too."""
    doc = _doc()
    doc["sections"].append({"src": "big", "mag": 2 ** 70})
    out = streamed(doc, False)
    assert out == dumps_jser(doc, False)
    assert out.startswith(b'{"sections": [null, {"src": "a.tif", ')


def test_a_section_nested_to_orjson_limit_matches():
    """orjson's nesting limit counts the levels a section sits under."""
    deep = []
    node = deep
    for _ in range(252):
        child = []
        node.append(child)
        node = child
    doc = {"sections": [{"src": "x", "deep": deep}], "series": {}, "log": ""}
    assert streamed(doc, False) == dumps_jser(doc, False)


# --------------------------------------------------------------------------
# a save that fails partway leaves the old file alone
# --------------------------------------------------------------------------

def test_an_unreadable_last_section_fails_the_save_and_keeps_the_old_file(tmp_path):
    """The earlier sections are already in the temp file when this one fails."""
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        good = open(series.jser_fp, "rb").read()

        last = max(series.sections)
        with open(os.path.join(series.hidden_dir, series.sections[last]), "wb") as f:
            f.write(b"{not json")

        with pytest.raises(SeriesSaveError):
            series.saveJser()

        assert open(series.jser_fp, "rb").read() == good
        assert temp_files(series.jser_fp) == []
    finally:
        series.close()


def test_a_section_file_gone_mid_save_fails_the_save_and_keeps_the_old_file(
        tmp_path, monkeypatch):
    """Deleted after the pre-flight check passed, while the stream is running."""
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        good = open(series.jser_fp, "rb").read()

        snums = sorted(series.sections)
        doomed = os.path.join(series.hidden_dir, series.sections[snums[len(snums) // 2]])
        first = os.path.join(series.hidden_dir, series.sections[snums[0]])
        real_open = open

        def open_and_delete(fp, *args, **kwargs):
            if fp == first and os.path.exists(doomed):
                os.remove(doomed)
            return real_open(fp, *args, **kwargs)

        monkeypatch.setattr("builtins.open", open_and_delete)
        with pytest.raises(SeriesSaveError):
            series.saveJser()
        monkeypatch.undo()

        assert open(series.jser_fp, "rb").read() == good
        assert temp_files(series.jser_fp) == []
    finally:
        series.leave_open = False
        series.close()


# --------------------------------------------------------------------------
# the save really streams
# --------------------------------------------------------------------------

def synthetic_series(tmp_path, n_sections=50, section_kb=100):
    """A real series whose hidden dir holds `n_sections` files of about `section_kb` KB."""
    series = open_copy(tmp_path, FIXTURES[1])
    base = fast_loads(open(
        os.path.join(series.hidden_dir, series.sections[min(series.sections)]), "rb"
    ).read())
    for filename in series.sections.values():
        os.remove(os.path.join(series.hidden_dir, filename))
    series.sections.clear()

    rng = random.Random(437)
    section = dict(base)
    section["contours"] = {}
    raw = b""
    while len(raw) < section_kb * 1024:
        name = f"obj{len(section['contours']):04d}"
        section["contours"][name] = [
            [
                [round(rng.uniform(0, 50), 6) for _ in range(60)],
                [round(rng.uniform(0, 50), 6) for _ in range(60)],
                [255, 0, 0], True, False, False, "none", [],
            ]
            for _ in range(5)
        ]
        raw = json.dumps(section).encode()
    for snum in range(n_sections):
        filename = f"{series.name}.{snum}"
        with open(os.path.join(series.hidden_dir, filename), "wb") as f:
            f.write(raw)
        series.sections[snum] = filename
    series.save()
    return series


def test_a_save_holds_far_less_than_the_file_in_memory(tmp_path):
    """Reading every section first held about five times the file size.

    Measured on 200 sections of 200 KB: 203 MB peak before, 3.3 MB after, for a
    39 MB file. Here, 100 sections of 100 KB make a file of about 9.7 MB, and
    the streaming path peaks near 1.8 MB however many sections there are. The
    bound is half the file size: the old path misses it by about ten times, and
    the streaming path clears it by more than two and a half times.
    """
    series = synthetic_series(tmp_path, n_sections=100)
    try:
        tracemalloc.start()
        try:
            series.saveJser()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        size = os.path.getsize(series.jser_fp)
        assert size > 8 * 1024 * 1024
        assert peak < size / 2, f"peak {peak} bytes for a {size} byte file"
    finally:
        series.close()


def test_a_save_writes_the_temp_file_in_pieces(tmp_path, monkeypatch):
    """The temp file is written section by section, not handed one block of bytes."""
    series = synthetic_series(tmp_path, n_sections=20, section_kb=10)
    writes = []
    real_atomic = series_mod._atomicWrite

    class Counting:
        def __init__(self, f):
            self.f = f

        def write(self, b):
            writes.append(len(b))
            return self.f.write(b)

        def __getattr__(self, name):
            return getattr(self.f, name)

    def counting_atomic(fp, data):
        if fp != series.jser_fp:  # the .ser in the hidden dir
            return real_atomic(fp, data)
        assert callable(data), "the save built the whole file before writing it"
        return real_atomic(fp, lambda f: data(Counting(f)))

    monkeypatch.setattr(series_mod, "_atomicWrite", counting_atomic)
    try:
        series.saveJser()
        assert len(writes) > len(series.sections)
        assert max(writes) < os.path.getsize(series.jser_fp) / 10
    finally:
        monkeypatch.undo()
        series.close()


# --------------------------------------------------------------------------
# every way the streaming save can fail leaves the old file as it was
# --------------------------------------------------------------------------

class RecordingNotifier(NullNotifier):
    def __init__(self):
        self.errors = []

    def notify_error(self, message, report):
        self.errors.append(message)
        return True


@pytest.fixture
def saved(tmp_path):
    """A series saved once, so there is a good .jser to keep, and its bytes."""
    series = open_copy(tmp_path, FIXTURES[1])
    series.saveJser()
    notifier = RecordingNotifier()
    series.setNotifier(notifier)
    good = open(series.jser_fp, "rb").read()
    yield series, good, notifier
    series.leave_open = False
    series.close()


def assert_untouched(series, good):
    assert open(series.jser_fp, "rb").read() == good
    assert temp_files(series.jser_fp) == []


def assert_save_failed_shown(notifier):
    assert len(notifier.errors) == 1
    assert "Save failed" in notifier.errors[0]
    assert "existing file was left unchanged" in notifier.errors[0]


def lone_surrogate_in_last_section(series):
    """orjson cannot encode a lone surrogate, so the save takes the stdlib pass."""
    fp = os.path.join(series.hidden_dir, series.sections[max(series.sections)])
    data = json.loads(open(fp, "rb").read())
    data["note"] = "\ud800"
    with open(fp, "w") as f:
        f.write(json.dumps(data))


def failing_writes(monkeypatch, should_fail):
    """Wrap the temp file so `should_fail(state)` can end a write with ENOSPC."""
    real_write_jser = series_mod.write_jser
    state = {"writes": 0, "truncated": False}

    class DiskFull:
        def __init__(self, f):
            self.f = f

        def write(self, b):
            state["writes"] += 1
            if should_fail(state):
                raise OSError(errno.ENOSPC, "No space left on device")
            return self.f.write(b)

        def writelines(self, lines):
            for line in lines:
                self.write(line)

        def truncate(self, *args):
            state["truncated"] = True
            state["writes"] = 0
            return self.f.truncate(*args)

        def __getattr__(self, name):
            return getattr(self.f, name)

    monkeypatch.setattr(
        series_mod, "write_jser",
        lambda f, *a, **k: real_write_jser(DiskFull(f), *a, **k),
    )
    return state


@pytest.mark.parametrize("nth", [1, 2, 5])
def test_a_full_disk_mid_stream_keeps_the_old_file(saved, monkeypatch, nth):
    series, good, notifier = saved
    failing_writes(monkeypatch, lambda st: st["writes"] == nth)

    with pytest.raises(OSError) as excinfo:
        series.saveJser()

    assert excinfo.value.errno == errno.ENOSPC
    assert_untouched(series, good)
    assert_save_failed_shown(notifier)


def test_a_failure_in_the_stdlib_pass_keeps_the_old_file(saved, monkeypatch):
    series, good, notifier = saved
    lone_surrogate_in_last_section(series)
    state = failing_writes(
        monkeypatch, lambda st: st["truncated"] and st["writes"] == 2
    )

    with pytest.raises(OSError):
        series.saveJser()

    assert state["truncated"], "the save never reached the stdlib pass"
    assert_untouched(series, good)
    assert_save_failed_shown(notifier)


def test_the_stdlib_pass_on_its_own_matches_the_old_path(saved):
    series, _, _ = saved
    lone_surrogate_in_last_section(series)
    expected = old_path_bytes(series)
    assert b'{"sections": [' in expected[:20]

    series.saveJser()

    assert open(series.jser_fp, "rb").read() == expected


def test_an_fsync_failure_keeps_the_old_file(saved, monkeypatch):
    series, good, notifier = saved
    real_fsync = os.fsync

    def failing_fsync(fd):
        if temp_files(series.jser_fp):
            raise OSError(errno.EIO, "Input/output error")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        series.saveJser()
    monkeypatch.undo()

    assert_untouched(series, good)
    assert_save_failed_shown(notifier)


def test_a_replace_failure_keeps_the_old_file(saved, monkeypatch):
    series, good, notifier = saved
    real_replace = os.replace

    def failing_replace(src, dst):
        if dst == series.jser_fp:
            raise OSError(errno.EROFS, "Read-only file system")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        series.saveJser()
    monkeypatch.undo()

    assert_untouched(series, good)
    assert_save_failed_shown(notifier)


def test_an_unreadable_series_file_shows_save_failed_and_keeps_the_old_file(
        saved, monkeypatch):
    """The .ser is now read while the temp file is open, so its error is surfaced."""
    series, good, notifier = saved

    def guarded_open(fp, mode="r", *args, **kwargs):
        if fp == series.filepath and "r" in mode:
            raise PermissionError(errno.EACCES, "Permission denied", fp)
        return open(fp, mode, *args, **kwargs)

    monkeypatch.setattr(series_mod, "open", guarded_open, raising=False)
    with pytest.raises(PermissionError):
        series.saveJser()
    monkeypatch.undo()

    assert_untouched(series, good)
    assert_save_failed_shown(notifier)


# --------------------------------------------------------------------------
# a save started inside another save
# --------------------------------------------------------------------------

def test_a_save_started_during_a_save_is_refused_and_the_file_stays_whole(tmp_path):
    """The progress dialog lets queued events run, so a Save can arrive mid-save.

    Both saves used one ``<jser>.tmp``: the inner save replaced the .jser with
    it, the outer save went on writing into what was now the user's file, and
    the result was invalid JSON under a message saying the file was unchanged.
    """
    series = open_copy(tmp_path, FIXTURES[0])
    notifier = RecordingNotifier()
    series.setNotifier(notifier)
    try:
        series.save()
        outer_bytes = old_path_bytes(series)
        inner = {}

        class SaveFromProgress(NullProgressReporter):
            calls = 0

            def set_progress(self, percent):
                SaveFromProgress.calls += 1
                if SaveFromProgress.calls != 50:
                    return
                # change a section's length, so a mix of the two saves cannot
                # line up, then save again as a queued Save event would
                fp = os.path.join(series.hidden_dir, series.sections[min(series.sections)])
                data = json.loads(open(fp, "rb").read())
                data["pad"] = "x" * 5000
                with open(fp, "w") as f:
                    f.write(json.dumps(data))
                inner["bytes"] = old_path_bytes(series)
                try:
                    series.saveJser()
                    inner["result"] = "saved"
                except SeriesSaveError as e:
                    inner["result"] = e

        series.setProgressReporter(SaveFromProgress)
        series.saveJser()
        series.setProgressReporter(NullProgressReporter)

        written = open(series.jser_fp, "rb").read()
        json.loads(written)
        assert written in (outer_bytes, inner["bytes"])
        assert written == outer_bytes, "the inner save was refused, so the outer one wrote"
        assert isinstance(inner["result"], SeriesSaveError)
        assert len(notifier.errors) == 1
        assert "already being saved" in notifier.errors[0]
        assert "left unchanged" not in notifier.errors[0]
        assert "wrote nothing" in notifier.errors[0]
        assert temp_files(series.jser_fp) == []

        # the guard is released: the next save goes through and picks up the edit
        series.saveJser()
        assert open(series.jser_fp, "rb").read() == old_path_bytes(series)
    finally:
        series.close()


def test_a_refusal_that_reaches_the_outer_save_stops_it_cleanly(tmp_path):
    """If the nested refusal is not caught, the outer save fails like any other.

    The old file is kept, no temp file is left, and the only message shown is
    the refusal, which says nothing about the outer save that could turn false.
    """
    series = open_copy(tmp_path, FIXTURES[0])
    notifier = RecordingNotifier()
    series.setNotifier(notifier)
    try:
        series.saveJser()
        good = open(series.jser_fp, "rb").read()

        class SaveFromProgress(NullProgressReporter):
            calls = 0

            def set_progress(self, percent):
                SaveFromProgress.calls += 1
                if SaveFromProgress.calls == 50:
                    series.saveJser()

        series.setProgressReporter(SaveFromProgress)
        with pytest.raises(SeriesSaveError):
            series.saveJser()
        series.setProgressReporter(NullProgressReporter)

        assert open(series.jser_fp, "rb").read() == good
        assert temp_files(series.jser_fp) == []
        assert len(notifier.errors) == 1
        assert notifier.errors[0].startswith("Save skipped")
    finally:
        series.close()


def test_two_overlapping_atomic_writes_do_not_share_a_temp_file(tmp_path):
    """Even without the guard, the destination ends up as one write's bytes."""
    fp = str(tmp_path / "target.jser")
    with open(fp, "wb") as f:
        f.write(b"old")

    def outer(f):
        f.write(b'{"outer": [')
        series_mod._atomicWrite(fp, b'{"inner": true}')
        f.write(b"1]}")

    series_mod._atomicWrite(fp, outer)

    assert open(fp, "rb").read() == b'{"outer": [1]}'
    assert temp_files(fp) == []


@pytest.mark.skipif(os.name == "nt", reason="a 246 character name passes MAX_PATH")
def test_a_series_name_as_long_as_main_allows_still_saves(tmp_path):
    """246 characters is the longest name whose ``<name>.jser.tmp`` fit in 255.

    A temp name built from the series name plus a unique tail pushed that
    over the limit and the save failed with "File name too long".
    """
    name = "n" * 246
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURES[1], fp)
    series = reopen_at(fp)
    try:
        series.saveJser()
        json.loads(open(fp, "rb").read())
        assert temp_files(fp) == []
        assert temp_files(series.filepath) == []
    finally:
        series.close()

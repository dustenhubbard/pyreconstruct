"""Regression tests for the undo-baseline encoding bug (Finding 1).

The fork writes section files as RAW UTF-8 bytes (orjson ``fast_dumps``, binary
mode). When a section is clean, ``SectionStates.initialize`` copies those bytes
verbatim into the ``.s0`` undo baseline (``shutil.copyfile``), so the baseline
also holds raw UTF-8. ``FieldState.getContours`` / ``getModifiedContours`` then
read that baseline back in TEXT mode.

Before the fix those reads passed no ``encoding=``, so they used the platform
locale codec. On a non-UTF-8 locale (Windows cp1252 is the default) a non-ASCII
object name made the read either:
  * raise UnicodeDecodeError (bytes not decodable as cp1252), crashing the undo; or
  * decode into mojibake, so the restored key no longer matched the real object
    name -- and in the multi-undo path the real contour was then overwritten
    with an EMPTY ``Contour`` and persisted on the next save (silent data loss).

These tests exercise the REAL save path (``section.save`` -> raw UTF-8 on disk),
build the real ``.s0`` baseline via ``SectionStates``, and force the readers
through a cp1252-defaulting scenario by patching ``builtins.open`` so any
text-mode open WITHOUT an explicit ``encoding=`` falls back to cp1252 (exactly
what a Windows locale does). The patched readers pass ``encoding="utf-8"``
explicitly, so they are immune; the unpatched readers were not -- these tests
FAIL on the pre-fix code (crash or empty contour) and PASS after.

The object name mixes characters that are NOT representable in cp1252 ("č", the
CJK "李") so the raw UTF-8 bytes genuinely cannot round-trip through cp1252 --
0x9D inside the UTF-8 encoding of "李" is undefined in cp1252 and raises on
decode, matching the field report.
"""
import os
import shutil
import builtins

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

OBJ = "objekt-č-ñ-李"          # non-ASCII object name; not cp1252-representable
OTHER = "plain_ascii_obj"      # an ASCII object edited first (multi-undo setup)


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    series.setProgressReporter(NullProgressReporter)
    return series


def _make_trace(name, pts):
    from PyReconstruct.modules.datatypes import Trace
    t = Trace(name, (255, 0, 0))
    for p in pts:
        t.add(p)
    return t


@pytest.fixture
def force_cp1252(monkeypatch):
    """Make every text-mode open() with no explicit encoding default to cp1252,
    reproducing a Windows locale. Binary opens and explicit-encoding opens are
    untouched -- so the fixed readers (encoding='utf-8') keep working and only
    the unfixed, locale-defaulting reads break."""
    real_open = builtins.open

    def fake_open(file, mode="r", *args, **kwargs):
        if "b" not in mode and kwargs.get("encoding") is None and len(args) < 4:
            kwargs["encoding"] = "cp1252"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    return fake_open


def _clean_section_with_obj(series, snum):
    """Add a non-ASCII-named object to a section and persist it through the
    real save path, then clear tracking so the section is 'clean' -- which is
    exactly when initialize() copies the on-disk UTF-8 bytes as the baseline."""
    section = series.loadSection(snum)
    section.addTrace(_make_trace(OBJ, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]))
    section.save()
    section.clearTracking()
    # The bug only exists when section files hold RAW (non-\u-escaped) UTF-8 --
    # i.e. the orjson backend. Without orjson, fast_dumps falls back to
    # json.dumps(...).encode() (ensure_ascii=True), so the file is pure ASCII,
    # the .s0 baseline is ASCII, and no locale can corrupt it. Skip rather than
    # emit a misleading failure in that (non-production) configuration.
    import PyReconstruct.modules.constants.fast_json as fj
    if not (fj._HAVE_ORJSON and fj.orjson is not None):
        pytest.skip("raw-UTF-8 section bytes require the orjson backend")
    with open(section.filepath, "rb") as f:
        assert "李".encode("utf-8") in f.read()   # sanity: really raw UTF-8
    return section


def test_single_undo_restores_non_ascii_contour(tmp_path, force_cp1252):
    """One edit + undo: the baseline .s0 (raw UTF-8) is read back to restore the
    section. Under a cp1252 locale the unfixed reader crashes/mojibakes; the fix
    restores the exact non-ASCII object with its trace intact."""
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    series = _load_series(tmp_path)
    snum = next(iter(series.sections))
    section = _clean_section_with_obj(series, snum)

    states = SectionStates(section, series)   # initialize -> UTF-8 .s0 baseline

    # edit: delete the object's only trace, then record the undo state
    section.removeTrace(section.contours[OBJ][0])
    states.addState(section, series)
    assert len(section.contours[OBJ]) == 0    # object now emptied

    states.undoState(section, series)         # <-- reads the UTF-8 baseline

    assert OBJ in section.contours, "undo lost the non-ASCII object entirely"
    assert len(section.contours[OBJ]) == 1, \
        "undo restored an EMPTY contour instead of the real one"
    assert section.contours[OBJ][0].points[:3] == [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0)
    ]
    series.close()


def test_multi_undo_never_replaces_non_ascii_with_empty(tmp_path, force_cp1252):
    """Multi-undo path: the non-ASCII object is restored from the FIRST (.s0)
    baseline while a later in-memory state holds a different object. The pre-fix
    bug here is the silent one -- the mojibaked key fails to match, so the real
    contour is overwritten with an empty Contour(name). Assert it never is."""
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    series = _load_series(tmp_path)
    snum = next(iter(series.sections))
    section = _clean_section_with_obj(series, snum)

    states = SectionStates(section, series)   # baseline holds OBJ (+ fixture objs)

    # edit 1: touch a DIFFERENT (ascii) object so the first in-memory undo state
    # does NOT contain OBJ -> OBJ must be resolved from the .s0 baseline
    section.addTrace(_make_trace(OTHER, [(2.0, 2.0), (3.0, 2.0), (3.0, 3.0)]))
    states.addState(section, series)

    # edit 2: now modify OBJ (delete its trace)
    section.removeTrace(section.contours[OBJ][0])
    states.addState(section, series)
    assert len(states.undo_states) == 2

    states.undoState(section, series)         # <-- multi-undo, reads UTF-8 .s0

    assert OBJ in section.contours
    assert len(section.contours[OBJ]) == 1, \
        "multi-undo replaced the real non-ASCII contour with an EMPTY one"
    assert section.contours[OBJ][0].points[:3] == [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0)
    ]
    series.close()


def test_modified_contours_reads_non_ascii_key_under_cp1252(tmp_path, force_cp1252):
    """getModifiedContours() also reads the baseline in text mode; under cp1252
    the unfixed read crashed. It must return the exact UTF-8 object name."""
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    series = _load_series(tmp_path)
    snum = next(iter(series.sections))
    section = _clean_section_with_obj(series, snum)

    states = SectionStates(section, series)
    names = states.current_state.getModifiedContours()   # reads .s0

    assert OBJ in names, "baseline modified-name read dropped/mangled the UTF-8 key"
    series.close()

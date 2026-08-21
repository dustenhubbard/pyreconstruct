"""Brightness/contrast profile migration, and what the section lock protects.

Three findings that share one data path -- the brightness/contrast values that
live on a section next to its transform, and the lock that sits over both.

1. **The legacy brightness/contrast migration destroyed named profiles.**
   ``Section.updateJSON`` folds the pre-profiles scalar ``brightness`` /
   ``contrast`` pair into ``brightness_contrast_profiles``. It did so by
   *assigning* a fresh one-key dict, discarding every other named profile on
   the section. ``getDict()`` never writes the scalars back, so the migration
   fired on every open only until the first save -- and that save, having
   dropped the scalars, made the loss of the other profiles permanent. This is
   inherited from upstream, not fork-introduced.

   The fix merges instead of replacing. Whether the scalars override an
   existing ``default`` is decided by whether the file carried a profiles dict
   at all: a pre-profiles file's scalars *are* its default, while a file that
   already has profiles is authoritative and is left alone.

2. **Sections locking on open is intentional, not a bug** -- pinned here so it
   is not "fixed" later. ``openJser`` sets ``align_locked = True`` on every
   section as it unpacks, ignoring the stored value. That is fail-safe: it
   protects alignments on every open, and honouring a stored ``False`` would
   remove that protection. The hidden-dir fast path does honour the stored
   value, correctly -- it resumes a live working directory rather than opening
   a file, so re-locking there would silently discard a lock the user cleared
   mid-session.

3. **Brightness/contrast is not gated on the lock.** The lock protects
   alignment. The section table used to refuse ``setBC`` / ``matchBC`` /
   ``optimizeBC`` on a locked section, which made the lock mean "read-only
   section" -- something it already was not, since the same lock permits
   copying traces onto a locked section and the field's own brightness and
   contrast shortcuts never checked it. The exemption is deliberately narrow:
   thickness, source image, and reordering stay gated, and every transform
   path stays gated.
"""
import json
import os
import shutil
import types

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _section_doc(**overrides):
    """A minimal but complete section dict in the current schema."""
    doc = {
        "src": "a.tif",
        "brightness_contrast_profiles": {"default": [0, 0]},
        "mag": 0.00254,
        "align_locked": True,
        "tforms": {"default": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]},
        "thickness": 0.05,
        "contours": {},
        "flags": [],
        "calgrid": False,
    }
    doc.update(overrides)
    return doc


def _write_jser(tmp_path, sections, name="bc.jser"):
    """Write a two-key .jser (``series`` + ``sections``) and return its path."""
    from PyReconstruct.modules.datatypes.series import Series

    series = Series.getEmptyDict()
    series["log_set"] = []
    doc = {
        "series": series,
        "sections": list(sections),
        "log": "Date, Time, User, Obj, Sections, Event",
    }
    fp = str(tmp_path / name)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return fp


def _open(fp):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


# ===========================================================================
# FINDING 1 -- the migration must merge, not replace
# ===========================================================================

def test_legacy_scalars_migrate_into_default_when_there_are_no_profiles():
    """The migration's actual job still works: a pre-profiles section's scalars
    become its ``default`` profile."""
    from PyReconstruct.modules.datatypes.section import Section

    sd = _section_doc()
    del sd["brightness_contrast_profiles"]
    sd["brightness"] = -12
    sd["contrast"] = 34.0

    Section.updateJSON(sd, 0)

    assert dict(sd["brightness_contrast_profiles"]) == {"default": (-12, 34)}
    assert sd["contrast"] == 34, "contrast is coerced to int"


def test_legacy_scalars_do_not_destroy_other_named_profiles():
    """THE BUG. Named profiles must survive the legacy migration.

    A real workflow: profiles named after alignments. Before the fix the whole
    dict was replaced by a single ``default`` key and every other profile was
    gone.
    """
    from PyReconstruct.modules.datatypes.section import Section

    profiles = {
        "default": [3, 4],
        "align_a": [10, 20],
        "align_b": [-30, -40],
        "dim_for_tracing": [-80, 5],
    }
    sd = _section_doc(brightness_contrast_profiles=dict(profiles))
    sd["brightness"] = -12
    sd["contrast"] = 34

    Section.updateJSON(sd, 0)

    got = sd["brightness_contrast_profiles"]
    for name in ("align_a", "align_b", "dim_for_tracing"):
        assert name in got, f"named profile {name!r} was destroyed"
        assert list(got[name]) == profiles[name], f"profile {name!r} was altered"
    # and the pre-existing default is authoritative over the stale scalars
    assert list(got["default"]) == [3, 4]


def test_legacy_scalars_fill_a_missing_default_without_touching_others():
    """A profiles dict that somehow has no ``default`` gets one from the
    scalars, and its other profiles are still untouched."""
    from PyReconstruct.modules.datatypes.section import Section

    sd = _section_doc(brightness_contrast_profiles={"align_a": [10, 20]})
    sd["brightness"] = 7
    sd["contrast"] = 8

    Section.updateJSON(sd, 0)

    got = sd["brightness_contrast_profiles"]
    assert list(got["default"]) == [7, 8]
    assert list(got["align_a"]) == [10, 20]


def test_a_non_dict_profiles_value_is_still_repaired():
    """The old wholesale assignment repaired a corrupt value by accident; a
    merge must not crash on one."""
    from PyReconstruct.modules.datatypes.section import Section

    for bad in (None, 0, "default", []):
        sd = _section_doc(brightness_contrast_profiles=bad)
        sd["brightness"] = 5
        sd["contrast"] = 6
        Section.updateJSON(sd, 0)
        assert dict(sd["brightness_contrast_profiles"]) == {"default": (5, 6)}


def test_named_profiles_survive_repeated_open_and_save_cycles(tmp_path):
    """End to end, over TWO cycles, which is where this stops being cosmetic.

    ``saveJser`` reads each section file out of the hidden dir *verbatim*
    (``fast_loads`` of the raw bytes) rather than through ``Section.getDict``,
    and ``updateJSON`` leaves the legacy scalars in the dict it wrote. So a
    section the user never individually edited keeps its ``brightness`` /
    ``contrast`` scalars across a save -- and therefore hits the migration
    again on the next open, and the one after that.

    That is the real shape of the defect: not "once, until the first save", but
    once per open, for as long as the scalars remain. Only a section that goes
    through ``Section.save()`` drops them, because that path does use
    ``getDict``.
    """
    profiles = {
        "default": [3, 4],
        "align_a": [10, 20],
        "align_b": [-30, -40],
    }
    sd = _section_doc(brightness_contrast_profiles=dict(profiles))
    sd["brightness"] = -12
    sd["contrast"] = 34
    fp = _write_jser(tmp_path, [sd])

    for cycle in (1, 2):
        series = _open(fp)
        try:
            section = series.loadSection(0)
            assert set(section.bc_profiles) == set(profiles), (
                f"cycle {cycle}: profiles were lost while unpacking"
            )
            series.saveJser()
        finally:
            series.close()

        with open(fp, "rb") as f:
            saved = json.load(f)
        row = saved["sections"][0]
        got = row["brightness_contrast_profiles"]
        assert set(got) == set(profiles), f"cycle {cycle}: the save lost profiles"
        for name, value in profiles.items():
            assert list(got[name]) == value, (
                f"cycle {cycle}: profile {name!r} changed value"
            )
        # the scalars are still there, which is exactly why cycle 2 matters
        assert row["brightness"] == -12 and row["contrast"] == 34, (
            "legacy scalars unexpectedly dropped; the repeat-per-open exposure "
            "this test exists for would no longer be reachable this way"
        )


# ===========================================================================
# FINDING 2 -- locking on open is intended; the fast path honouring the
#              stored value is also intended
# ===========================================================================

def test_open_jser_locks_every_section_regardless_of_stored_value(tmp_path):
    """Unpacking a .jser locks every section. Fail-safe and deliberate."""
    fp = _write_jser(
        tmp_path,
        [
            _section_doc(align_locked=False),
            _section_doc(align_locked=True),
            _section_doc(align_locked=False),
        ],
        name="locks.jser",
    )

    series = _open(fp)
    try:
        for snum in (0, 1, 2):
            assert series.loadSection(snum).align_locked is True, (
                f"section {snum} came up unlocked from an unpack"
            )
    finally:
        series.close()


def test_hidden_dir_resume_keeps_a_section_the_user_unlocked(tmp_path):
    """The recovery/resume path reopens a live working directory, so an unlock
    made during that session must survive -- it must NOT be re-locked."""
    fp = _write_jser(
        tmp_path, [_section_doc(), _section_doc()], name="resume.jser"
    )

    series = _open(fp)
    section = series.loadSection(1)
    section.align_locked = False
    section.save()
    hidden = series.getwdir()
    assert os.path.isdir(hidden)

    # reopen WITHOUT clearing the hidden dir: this takes the resume fast path
    resumed = _open(fp)
    try:
        assert resumed.leave_open is True, "expected the hidden-dir fast path"
        assert resumed.loadSection(1).align_locked is False, (
            "the resume path re-locked a section the user had unlocked"
        )
        assert resumed.loadSection(0).align_locked is True
    finally:
        shutil.rmtree(hidden, ignore_errors=True)


# ===========================================================================
# FINDING 3 -- brightness/contrast is exempt from the lock; nothing else is
# ===========================================================================

def _table_stub(monkeypatch, locked_sections=(), selected=(1, 2)):
    """A duck-typed SectionTableWidget, so no Qt event loop is needed."""
    from PyReconstruct.modules.gui.table import section as tbl

    notified = []
    monkeypatch.setattr(tbl, "notify", lambda *a, **k: notified.append(a))

    sections = {
        n: types.SimpleNamespace(
            brightness=0, contrast=0, thickness=0.05, save_count=0
        )
        for n in selected
    }
    for s in sections.values():
        s.save = (lambda s=s: setattr(s, "save_count", s.save_count + 1))

    data = {
        "sections": {
            n: {"locked": n in locked_sections, "thickness": 0.05}
            for n in selected
        }
    }
    def _enumerate_sections(show_progress=True, message="", series_states=None,
                            breakable=True, section_numbers=None):
        """The double's stand-in for Series.enumerateSections.

        The bulk section handlers iterate through it rather than calling
        loadSection in a hand-written loop, because it is what drives the
        progress bar (see test_section_list_progress.py). It yields
        (snum, section) over the requested subset; this double drops the
        progress arguments, which is exactly what NullProgressReporter does
        headless.
        """
        wanted = list(sections) if section_numbers is None else list(section_numbers)
        return [(n, sections[n]) for n in wanted if n in sections]

    stub = types.SimpleNamespace(
        series=types.SimpleNamespace(
            data=data,
            loadSection=lambda n: sections[n],
            enumerateSections=_enumerate_sections,
            addLog=lambda *a, **k: None,
        ),
        manager=types.SimpleNamespace(updateSections=lambda nums: None),
        mainwindow=types.SimpleNamespace(
            saveAllData=lambda: None,
            seriesModified=lambda *a: None,
            field=types.SimpleNamespace(
                reload=lambda: None,
                section=types.SimpleNamespace(brightness=41, contrast=42),
            ),
            optimizeBC=lambda nums: optimize_calls.append(list(nums)),
        ),
        getSelected=lambda: list(selected),
        setBC_calls=[],
    )
    optimize_calls = []
    stub.optimize_calls = optimize_calls
    stub.setBC = lambda *a, **k: stub.setBC_calls.append((a, k))
    return tbl, stub, sections, notified


def test_setbc_applies_to_a_locked_section(monkeypatch):
    """A locked section still accepts a brightness/contrast change."""
    tbl, stub, sections, notified = _table_stub(monkeypatch, locked_sections=(1, 2))

    tbl.SectionTableWidget.setBC(
        stub, section_numbers=[1, 2], b=25, c=-10, log_event=False
    )

    assert notified == [], f"user was told to unlock: {notified}"
    for n in (1, 2):
        assert (sections[n].brightness, sections[n].contrast) == (25, -10)
        assert sections[n].save_count == 1, "the change was not persisted"


def test_matchbc_and_optimizebc_proceed_on_a_locked_section(monkeypatch):
    tbl, stub, _sections, notified = _table_stub(monkeypatch, locked_sections=(1, 2))

    tbl.SectionTableWidget.matchBC(stub)
    assert notified == []
    assert stub.setBC_calls == [(([1, 2], 41, 42), {})], (
        "matchBC did not reach setBC"
    )

    tbl.SectionTableWidget.optimizeBC(stub)
    assert notified == []
    assert stub.optimize_calls == [[1, 2]], "optimizeBC did not reach the window"


def test_the_exemption_did_not_widen_to_thickness(monkeypatch):
    """Guard against over-broadening: thickness is NOT brightness/contrast and
    stays gated on the lock."""
    tbl, stub, sections, notified = _table_stub(monkeypatch, locked_sections=(1,))

    tbl.SectionTableWidget.editThickness(stub, log_event=False)

    assert len(notified) == 1, "a locked section accepted a thickness edit"
    assert sections[1].save_count == 0


def test_the_exemption_did_not_widen_to_the_transform(monkeypatch):
    """Guard against over-broadening: the lock still blocks a transform change,
    which is the thing it exists to protect."""
    from PyReconstruct.modules.gui.main import field_widget_4_data as fw
    from PyReconstruct.modules.datatypes import Transform

    base = Transform([1, 0, 0, 0, 1, 0])
    section = types.SimpleNamespace(align_locked=True, tform=base, n=1)
    stub = types.SimpleNamespace(
        section=section,
        section_layer=types.SimpleNamespace(section=section),
        propagate_tform=False,
        series=types.SimpleNamespace(addLog=lambda *a: pytest.fail("logged")),
        generateView=lambda: pytest.fail("regenerated the view"),
        saveState=lambda: pytest.fail("saved state"),
    )

    fw.FieldWidgetData.changeTform(stub, Transform([1, 0, 9, 0, 1, 9]))

    assert section.tform is base, "a locked section's transform was changed"

"""A legacy flag's ID must be the same every time the file is unpacked.

Flags did not always carry an ID. ``Section.updateJSON`` back-fills one for a
flag stored in the older 5- or 6-field form, and that migration runs on **every**
unpack of such a .jser -- ``Series.openJser`` calls it per section on the way to
the hidden working directory. It used to call ``Flag.generateID``, which is
random, so the same flag in the same file came out of two opens with two
different IDs.

Why that is not cosmetic. ``Flag.equals`` compares IDs and nothing else, and
``Series.importFlags`` deduplicates purely by ``equals``. A flag's ID is the only
thing that says "this is the same flag as that one", so an ID that does not
survive a trip through the file is an identity that does not survive it either.
Two people who each opened the same legacy .jser and saved it hold the same flag
under two IDs, and importing one series into the other stacks a duplicate on top
of every legacy flag -- same name, same coordinates, same comments -- rather than
merging them. ``test_import_no_longer_duplicates_a_shared_legacy_flag`` is that
scenario end to end, with an already-migrated flag as the control.

Why the ID is *derived* from the flag's content rather than generated once and
persisted. Persisting fixes only the single-copy case: the first save of one copy
of the file freezes that copy's random IDs, but a file opened read-only never
gets any, and two copies opened independently never agree, which is exactly the
import case above. A hash of the flag's own content agrees everywhere with no
save required. ``Flag.deriveID`` emits six characters from the same alphabet
``generateID`` uses, so a migrated ID is indistinguishable from a generated one.

A knock-on: a random ID landing in the file also made a save of a legacy series
non-reproducible, which is what ``tests/test_jser_canonical_format.py`` pins for
everything else. That file's fixture uses fully-migrated 7-field flags precisely
because the migration was random; the derivation is what would let it stop.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from PyReconstruct.modules.datatypes.flag import possible_chars
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import Series


FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

# the 6-field legacy form: name, x, y, color, comments, resolved
LEGACY6 = ["check this", 1.5, 2.5, [255, 0, 0],
           [["alice", "2026-01-01", "10:00:00", "have a look"]], False]
# the 5-field form predates `resolved` too
LEGACY5 = LEGACY6[:-1]


def _migrate(flags, snum=0):
    """Run one unpack's worth of migration and return the resulting IDs."""
    sd = Section.getEmptyDict()
    sd["flags"] = json.loads(json.dumps(flags))  # a deep copy per run
    Section.updateJSON(sd, snum)
    return [f[0] for f in sd["flags"]]


# --------------------------------------------------------------------------
# the ID is stable
# --------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [LEGACY6, LEGACY5], ids=["6-field", "5-field"])
def test_the_same_legacy_flag_migrates_to_the_same_id_every_time(flag):
    """The finding, directly: four unpacks, one ID."""
    ids = {_migrate([flag])[0] for _ in range(4)}
    assert len(ids) == 1, f"four unpacks produced {len(ids)} different IDs: {ids}"


def test_the_five_and_six_field_forms_agree():
    """The 5-field form is the 6-field form with `resolved` defaulted.

    They are the same flag, so they must migrate to the same ID -- otherwise a
    series upgraded through one path could not merge with one upgraded through
    the other.
    """
    assert _migrate([LEGACY5]) == _migrate([LEGACY6])


def test_a_migrated_id_looks_exactly_like_a_generated_one():
    """Six characters from `generateID`'s alphabet, so nothing downstream can
    tell a migrated flag from a native one."""
    id = _migrate([LEGACY6])[0]
    assert len(id) == 6
    assert set(id) <= set(possible_chars)


def test_an_already_migrated_flag_is_left_alone():
    """A 7-field flag carries its own ID and the migration must not touch it."""
    seven = ["ABC123"] + LEGACY6
    assert _migrate([seven]) == ["ABC123"]


# --------------------------------------------------------------------------
# ...but still tells flags apart
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    (0, "a different name"),
    (1, 99.5),               # x
    (2, 99.5),               # y
    (3, [0, 255, 0]),        # color
    (5, True),               # resolved
])
def test_a_different_flag_gets_a_different_id(field, value):
    other = list(LEGACY6)
    other[field] = value
    assert _migrate([LEGACY6]) != _migrate([other])


def test_the_same_flag_on_two_sections_gets_two_ids():
    """A flag is identified series-wide, so the section number is part of it."""
    assert _migrate([LEGACY6], snum=0) != _migrate([LEGACY6], snum=1)


def test_two_identical_flags_in_one_section_get_distinct_stable_ids():
    """Nothing stops a section holding the same flag twice, and IDs are what
    tells them apart, so a collision must be broken -- deterministically."""
    first = _migrate([LEGACY6, LEGACY6])
    assert first[0] != first[1]
    assert _migrate([LEGACY6, LEGACY6]) == first


def test_a_derived_id_never_displaces_one_already_in_the_file():
    """A hand-edited file can mix migrated and unmigrated flags."""
    reserved = _migrate([LEGACY6])[0]
    mixed = _migrate([[reserved] + LEGACY5 + [False], LEGACY6])
    assert mixed[0] == reserved
    assert mixed[1] != reserved


# --------------------------------------------------------------------------
# stable across processes, not just within one
# --------------------------------------------------------------------------

_DRIVER = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from PyReconstruct.modules.datatypes.section import Section
sd = Section.getEmptyDict()
sd["flags"] = json.loads(sys.argv[2])
Section.updateJSON(sd, 0)
print(sd["flags"][0][0])
'''


def _derive_in_subprocess(tmp_path, seed):
    driver = tmp_path / f"driver{seed}.py"
    driver.write_text(_DRIVER)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["QT_QPA_PLATFORM"] = "offscreen"
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    r = subprocess.run(
        [sys.executable, str(driver), repo, json.dumps([LEGACY6])],
        check=True, capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    return r.stdout.strip()


def test_the_id_is_the_same_in_a_separate_interpreter(tmp_path):
    """Different hash seeds, same ID.

    The guard against deriving from anything process-local: Python's built-in
    ``hash`` of a str is salted per process, so a derivation built on it would
    pass every test above and still hand two collaborators different IDs.
    """
    a = _derive_in_subprocess(tmp_path, seed=1)
    b = _derive_in_subprocess(tmp_path, seed=2)
    assert a and a == b
    assert a == _migrate([LEGACY6])[0]


# --------------------------------------------------------------------------
# end to end, through a real .jser
# --------------------------------------------------------------------------

def _legacy_jser(dst):
    """shapes1.jser with a pre-ID flag on every section."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    doc = json.loads(open(FIXTURE, "rb").read())
    for sd in doc["sections"]:
        if sd:
            sd["flags"] = [json.loads(json.dumps(LEGACY6))]
    with open(dst, "w") as f:
        json.dump(doc, f)
    return str(dst)


def _flag_ids(fp):
    series = Series.openJser(fp)
    try:
        return [f.id for _, sec in series.enumerateSections(show_progress=False)
                for f in sec.flags]
    finally:
        series.close()


def test_opening_the_same_legacy_jser_twice_yields_the_same_ids(tmp_path):
    """No save in between: the file on disk still has no IDs either time."""
    fp = _legacy_jser(tmp_path / "legacy.jser")
    first = _flag_ids(fp)
    assert first, "the fixture produced no flags"
    assert first == _flag_ids(fp)


def test_import_no_longer_duplicates_a_shared_legacy_flag(tmp_path):
    """The consequence, in the workflow that shows it.

    Two people copy one legacy .jser, each opens and saves it, then one imports
    the other's flags. Every flag is the same flag, so nothing should be added.
    Before the derivation this doubled the flag count on every section.
    """
    master = _legacy_jser(tmp_path / "master.jser")
    alice = str(tmp_path / "alice.jser")
    bob = str(tmp_path / "bob.jser")
    for fp in (alice, bob):
        shutil.copyfile(master, fp)
        Series.openJser(fp).saveJser(close=True)

    sa, sb = Series.openJser(alice), Series.openJser(bob)
    try:
        def count():
            return sum(len(sec.flags)
                       for _, sec in sa.enumerateSections(show_progress=False))
        before = count()
        assert before
        sa.importFlags(sb, (0, 10 ** 6), log_event=False)
        assert count() == before, "importing the same flags added duplicates"
    finally:
        sa.close()
        sb.close()

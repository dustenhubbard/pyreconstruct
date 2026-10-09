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
import hashlib
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

import PyReconstruct.modules.datatypes.flag as flag_module
from PyReconstruct.modules.datatypes.flag import Flag, possible_chars
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import Series


FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
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


def test_identical_flags_past_a_thousand_keep_stable_distinct_ids():
    """The salt range used to end at 1,000 and fall back to a random ID, so the
    1,001st identical flag changed on every open and was never checked against
    the others."""
    flags = [LEGACY6] * 1005
    first = _migrate(flags)
    assert len(set(first)) == 1005
    assert _migrate(flags) == first


def test_a_derived_id_never_displaces_one_already_in_the_file():
    """A hand-edited file can mix migrated and unmigrated flags."""
    reserved = _migrate([LEGACY6])[0]
    mixed = _migrate([[reserved] + LEGACY5 + [False], LEGACY6])
    assert mixed[0] == reserved
    assert mixed[1] != reserved


# --------------------------------------------------------------------------
# the IDs files already got, and what they cost
# --------------------------------------------------------------------------

# a second repeated flag, to interleave with LEGACY6
OTHER6 = ["look here", 3.0, 4.0, [0, 255, 0], [], True]


def _mixed_section():
    """Two repeated flags interleaved past 1,000, some distinct ones, a 5-field
    copy of LEGACY6, and a stored ID equal to the one LEGACY6's second copy
    derives on section 3."""
    flags = [["6AwcGS"] + LEGACY6]
    for i in range(1200):
        flags.append(LEGACY6 if i % 2 == 0 else OTHER6)
        if i % 100 == 0:
            flags.append([f"distinct {i}", float(i), 0.0, [1, 2, 3], [], False])
    flags.append(LEGACY5)
    return flags


def _digest(ids):
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def test_migrated_ids_match_the_ids_files_already_got():
    """Pinned against the IDs the migration produced before it kept salt
    progress. A file opened then and opened now must agree on every ID, or
    importing one into the other duplicates the flags again."""
    assert _migrate([LEGACY6] * 3, snum=3)[1] == "6AwcGS"

    same = _migrate([LEGACY6] * 1005)
    assert same[:3] == ["WUU3ie", "iphtw8", "edPPO5"]
    assert same[-2:] == ["vevIZI", "KOYks4"]
    assert _digest(same) == (
        "56a66ea0d5fdce998ac998593758d0d09a2ae6ae7365cfdf7325faaf2da2cff2"
    )

    mixed = _migrate(_mixed_section(), snum=3)
    assert len(mixed) == len(set(mixed)) == 1214
    assert mixed[0] == "6AwcGS"
    assert _digest(mixed) == (
        "42f814faa8e6aa5ee804df51e0c4e81d6cac9f71883ab3f30e4738b98528d56f"
    )


def test_the_migration_matches_deriving_one_flag_at_a_time():
    """``LegacyFlagIDs`` resumes each repeated flag's salt where it stopped.
    That must give the same IDs as ``Flag.deriveID`` from salt zero for every
    flag, with each result taken before the next."""
    flags = json.loads(json.dumps(_mixed_section()))
    taken = {f[0] for f in flags if len(f) == 7}
    expected = []
    for f in flags:
        if len(f) == 7:
            expected.append(f[0])
            continue
        if len(f) == 5:
            f = f + [False]
        flag_id = Flag.deriveID([3] + f, taken)
        taken.add(flag_id)
        expected.append(flag_id)
    assert _migrate(_mixed_section(), snum=3) == expected


def _count_hashes(monkeypatch):
    """Count calls to the hash the derivation uses. Returns a one-item list."""
    calls = [0]

    def counting_blake2b(*args, **kwargs):
        calls[0] += 1
        return hashlib.blake2b(*args, **kwargs)

    monkeypatch.setattr(
        flag_module, "hashlib", types.SimpleNamespace(blake2b=counting_blake2b)
    )
    return calls


def test_identical_flags_no_longer_repeat_the_search(monkeypatch):
    """Every identical flag used to restart at salt zero and rehash every salt
    the earlier copies took, so n copies cost about n**2 / 2 hashes: 12.5
    million for 5,000, on every open. Counted at the hash call, not timed.
    With no stored IDs and no collision among these candidates, each copy
    costs exactly one hash."""
    calls = _count_hashes(monkeypatch)
    n = 5000
    ids = _migrate([LEGACY6] * n)
    assert len(set(ids)) == n
    assert calls[0] == n, f"{n} identical flags took {calls[0]} hashes"


def test_a_collision_costs_one_more_hash(monkeypatch):
    """A flag whose salt-zero ID is already stored in the file takes the next
    salt, so it costs two hashes, not one."""
    salt_zero = _migrate([LEGACY6], snum=3)[0]
    calls = _count_hashes(monkeypatch)
    ids = _migrate([[salt_zero] + LEGACY6, LEGACY6], snum=3)
    assert ids[0] == salt_zero and ids[1] != salt_zero
    assert calls[0] == 2


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

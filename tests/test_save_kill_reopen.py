"""Kill a real process partway through Save, reopen, and check what survived.

``tests/save_kill_child.py`` opens a copy of a small series in its own process,
edits four of its five sections and one object attribute, and saves the way
Save (Cmd+S, Ctrl+S on Windows/Linux) does. It stops at one named point in the
save and this test SIGKILLs it there: no ``finally`` block, ``atexit`` hook or
buffered write runs after that. Two of the points force a partial write onto
disk rather than wait at a boundary; the child's docstring says which and why.

Then the folder is reopened both ways the window offers after a crash, each on
its own copy:

* declining the unsaved work: the working folder is deleted, as the window
  deletes it, and the .jser opens. The .jser must be exactly the series before
  the save or exactly the series after it.
* opening the unsaved work: the working folder opens, every section loads, and
  the .jser a save from it writes must be exactly the state the folder held at
  that point, listed per point in ``POINTS``.

"Exactly" is the whole .jser document, every section, the series and the
history, compared as parsed JSON. The only thing left out is the date and time
of each history line, which differ from run to run. The states compared against
come from finished runs of the same child: the fixture as checked in, the
finished save, and the finished save without the edit to the section on screen.
"""

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

pytestmark = pytest.mark.slow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "dev", "assets", "checker", "files", "shapes2.jser")
CHILD = os.path.join(ROOT, "tests", "save_kill_child.py")
NAME = "shapes2"

#: How long the child may take to reach its point. It takes under a second.
TIMEOUT = 120

TEMP_NAME = re.compile(r"\.save-[0-9a-f]{6}\.tmp")

# Each point, the state the .jser must hold after the kill, and the state the
# working folder must hold.
#   old          the fixture
#   new          the finished save
#   pre-current  the finished save without the edit to the section on screen,
#                whose working file had not been renamed into place
#   sections-ahead  the sections of "new" with the series file of
#                "pre-current": the section on screen was written to the
#                working folder and the series file after it was not. The
#                series file is the history, so this one entry is missing. A
#                crash between leaving a section and the next series write
#                leaves the same state; the two files are never written as one.
#   gone-or-new  no series file left to offer, or "new"
POINTS = {
    "section-replace": ("old", "pre-current"),
    "ser-replace": ("old", "sections-ahead"),
    "injected-jser-half-write": ("old", "new"),
    "injected-jser-flush-between-sections": ("old", "new"),
    "jser-before-rename": ("old", "new"),
    "jser-after-rename": ("new", "new"),
    "close-remove": ("new", "gone-or-new"),
}

class IncompleteWorkingFolder(Exception):
    """The working folder is offered as unsaved work with files already gone.

    A close that stops partway must leave no series file to offer, so this is
    the failure a close removing the series file late would show.
    """


def run_child(jser_fp, point):
    """Run the child to `point` and SIGKILL it there, or to the end for a control.

    Any other outcome is a plain test failure (pytest.fail).
    """
    control = point.startswith("none")
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    err_fp = jser_fp + ".child-stderr.txt"
    with open(err_fp, "w") as err:
        proc = subprocess.Popen(
            [sys.executable, CHILD, jser_fp, point],
            stdout=subprocess.PIPE, stderr=err, text=True, env=env,
            cwd=os.path.dirname(jser_fp),
        )
    lines = queue.Queue()

    def read():
        for line in proc.stdout:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    seen = []
    timed_out = False
    try:
        while True:
            try:
                line = lines.get(timeout=TIMEOUT)
            except queue.Empty:
                timed_out = True
                break
            if line is None:
                break
            seen.append(line)
            if line == f"AT {point}" or (control and line == "SAVED"):
                break
    finally:
        if not control or timed_out:
            proc.kill()
        proc.wait(timeout=60)
        proc.stdout.close()
    with open(err_fp) as f:
        stderr = f.read()
    os.remove(err_fp)

    if timed_out:
        pytest.fail(f"the child did not reach {point} in {TIMEOUT} s: {seen}\n{stderr}")
    if control:
        if proc.returncode != 0 or seen[-1:] != ["SAVED"]:
            pytest.fail(f"the control save {point} did not finish: {seen}\n{stderr}")
        return
    if seen[-1:] != [f"AT {point}"]:
        pytest.fail(f"the child never reached {point}: {seen}\n{stderr}")
    if os.name == "posix" and proc.returncode != -signal.SIGKILL:
        pytest.fail(f"the child was not SIGKILLed: {proc.returncode}\n{stderr}")


def open_series(jser_fp):
    series = Series.openJser(jser_fp, progress=NullProgressReporter, notifier=NullNotifier())
    assert series is not None
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


def document(jser_fp):
    """The whole .jser, parsed, with the date and time cut from each history line."""
    with open(jser_fp, "rb") as f:
        doc = json.loads(f.read())
    doc["log"] = [
        ", ".join(line.split(", ")[2:])
        for line in doc.get("log", "").splitlines() if line.strip()
    ]
    return doc


def hidden_dir(folder):
    return os.path.join(folder, f".{NAME}")


def clear_hidden(folder):
    """Delete the working folder the way the window does when unsaved work is declined."""
    hidden = hidden_dir(folder)
    if os.path.isdir(hidden):
        for f in os.listdir(hidden):
            os.remove(os.path.join(hidden, f))
        os.rmdir(hidden)


def open_jser_only(folder):
    """Decline the unsaved work, open the .jser (every section), close it again."""
    clear_hidden(folder)
    jser_fp = os.path.join(folder, f"{NAME}.jser")
    series = open_series(jser_fp)
    try:
        for snum in series.sections:
            series.loadSection(snum)
    finally:
        series.close()
    return document(jser_fp)


def has_working_series(folder):
    """Whether the window would offer the working folder as unsaved work."""
    hidden = hidden_dir(folder)
    return os.path.isdir(hidden) and any(f.endswith(".ser") for f in os.listdir(hidden))


def finished_save(base, control):
    folder = base / control
    folder.mkdir()
    shutil.copyfile(FIXTURE, folder / f"{NAME}.jser")
    run_child(str(folder / f"{NAME}.jser"), control)
    return open_jser_only(str(folder))


@pytest.fixture(scope="module")
def states(tmp_path_factory):
    """Every state a kill may leave, as whole documents (see POINTS)."""
    base = tmp_path_factory.mktemp("save-kill-states")
    (base / "old").mkdir()
    shutil.copyfile(FIXTURE, base / "old" / f"{NAME}.jser")
    old = open_jser_only(str(base / "old"))
    new = finished_save(base, "none")
    pre_current = finished_save(base, "none-without-current")
    sections_ahead = dict(pre_current, sections=new["sections"])

    # the states differ where they should, so an equal one is not luck. (Every
    # section differs from the fixture's: an open locks each section and
    # rewrites it in today's layout, edited or not.)
    assert [s == o for s, o in zip(pre_current["sections"], new["sections"])] == [
        True, True, True, False, True]
    assert new["log"] != pre_current["log"] != old["log"]
    assert len({json.dumps(d, sort_keys=True) for d in (
        old, new, pre_current, sections_ahead)}) == 4
    return {
        "old": old, "new": new, "pre-current": pre_current,
        "sections-ahead": sections_ahead,
    }


def kill_at(tmp_path, point):
    folder = tmp_path / "series"
    folder.mkdir()
    jser_fp = folder / f"{NAME}.jser"
    shutil.copyfile(FIXTURE, jser_fp)
    run_child(str(jser_fp), point)
    with open(FIXTURE, "rb") as a, open(jser_fp, "rb") as b:
        untouched = a.read() == b.read()
    return folder, untouched


def check_jser(folder, untouched, expect, states, tmp_path):
    """Decline the unsaved work: the .jser alone is the old series or the new one."""
    declined = tmp_path / "declined"
    shutil.copytree(folder, declined)
    got = open_jser_only(str(declined))
    if expect == "old":
        assert untouched, "the .jser was written before the save finished"
    assert got == states[expect], f"the .jser is not exactly the {expect} series"
    leftovers = [
        f for f in os.listdir(declined)
        if f != f"{NAME}.jser" and f != f".{NAME}"
    ]
    # a temp file left by the killed save is one a later open removes
    assert all(TEMP_NAME.fullmatch(f) for f in leftovers), leftovers


def check_working_folder(folder, expect, states, tmp_path):
    """Open the unsaved work: a save from it writes exactly the state it held."""
    accepted = tmp_path / "accepted"
    shutil.copytree(folder, accepted)
    if expect == "gone-or-new" and not has_working_series(str(accepted)):
        return  # nothing to offer: the window clears the folder and opens the .jser
    assert has_working_series(str(accepted)), "the working folder is not offered"
    want = states["new" if expect == "gone-or-new" else expect]

    hidden = hidden_dir(str(accepted))
    missing = [
        f"{NAME}.{snum}" for snum, section in enumerate(want["sections"])
        if section is not None and not os.path.isfile(os.path.join(hidden, f"{NAME}.{snum}"))
    ]
    if not os.path.isfile(os.path.join(hidden, "existing_log.csv")):
        missing.append("existing_log.csv")
    if missing:
        raise IncompleteWorkingFolder(f"offered as unsaved work without {missing}")

    series = open_series(str(accepted / f"{NAME}.jser"))
    try:
        for snum in series.sections:
            series.loadSection(snum)
        series.saveJser()
    finally:
        series.close()
    assert document(str(accepted / f"{NAME}.jser")) == want, (
        f"a save from the working folder is not exactly the {expect} state"
    )


@pytest.mark.parametrize("point", POINTS)
def test_kill_during_save_then_reopen(tmp_path, states, point):
    jser_expect, hidden_expect = POINTS[point]
    folder, untouched = kill_at(tmp_path, point)
    check_jser(folder, untouched, jser_expect, states, tmp_path)
    check_working_folder(folder, hidden_expect, states, tmp_path)


def test_a_mixed_series_matches_no_state(states):
    """The comparison is strict enough to see a series that is part old, part new."""
    new, old = states["new"], states["old"]

    def changed(doc, edit):
        doc = json.loads(json.dumps(doc))
        edit(doc)
        return doc

    def stale_section(doc):
        doc["sections"][3] = old["sections"][3]

    def recolored(doc):
        doc["sections"][2]["contours"]["kill_test"][0][2] = [0, 0, 0]  # color

    def history_short(doc):
        doc["log"] = doc["log"][:-1]

    def series_stale(doc):
        doc["series"] = old["series"]

    for edit in (stale_section, recolored, history_short, series_stale):
        mixed = changed(new, edit)
        assert mixed not in states.values(), edit.__name__

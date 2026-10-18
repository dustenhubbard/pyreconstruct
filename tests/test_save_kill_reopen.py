"""Kill a real process partway through Save, reopen, and check what survived.

``tests/save_kill_child.py`` opens a copy of a small series in its own process,
edits four of its five sections and one object attribute, and saves the way
Save (Cmd+S, Ctrl+S on Windows/Linux) does. It stops at one named point in the
save and this test SIGKILLs it there: no ``finally`` block, ``atexit`` hook or
buffered write runs after that.

Then the folder is reopened both ways the window offers after a crash, each on
its own copy:

* declining the unsaved work: the working folder is deleted, as the window
  deletes it, and the .jser opens. It must hold exactly the series before the
  save or exactly the series after it, never some sections of each.
* opening the unsaved work: the working folder opens. It must hold every edit
  that had reached it, every section, and the series history, and a save from
  it must write all of that to the .jser.

The states compared against are the fixture as checked in and the result of the
same child run with no kill.
"""

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

# Each point, what the .jser must hold after the kill, and what the working
# folder must hold. "pre-current" is the finished save without the edit to
# the section on screen, whose working file had not been renamed into place.
POINTS = {
    "section-replace": ("old", "pre-current"),
    "ser-replace": ("old", "new"),
    "jser-mid-write": ("old", "new"),
    "jser-between-sections": ("old", "new"),
    "jser-before-rename": ("old", "new"),
    "jser-after-rename": ("new", "new"),
    "close-remove": ("new", "gone-or-new"),
}

CLOSE_REMOVE_ISSUE = "https://github.com/dustenhubbard/pyreconstruct/issues/962"


def run_child(jser_fp, point):
    """Run the child to `point` and SIGKILL it there. Returns its stdout lines.

    Fails if the child finishes, dies or stalls before it reports the point.
    """
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
    try:
        while True:
            try:
                line = lines.get(timeout=TIMEOUT)
            except queue.Empty:
                pytest.fail(f"the child did not reach {point} in {TIMEOUT} s: {seen}")
            if line is None:
                break
            seen.append(line)
            if line == f"AT {point}" or (point == "none" and line == "SAVED"):
                break
    finally:
        if point != "none":
            proc.kill()
        proc.wait(timeout=60)
        proc.stdout.close()
    with open(err_fp) as f:
        stderr = f.read()
    os.remove(err_fp)

    if point == "none":
        assert proc.returncode == 0 and seen[-1:] == ["SAVED"], (seen, stderr)
    else:
        assert seen[-1:] == [f"AT {point}"], (
            f"the child never reached {point}: {seen}\n{stderr}"
        )
        if os.name == "posix":
            assert proc.returncode == -signal.SIGKILL, (proc.returncode, stderr)
    return seen


def open_series(jser_fp):
    series = Series.openJser(jser_fp, progress=NullProgressReporter, notifier=NullNotifier())
    assert series is not None
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


def content(series):
    """What a save must keep, compared exactly: every section's traces, and the attribute."""
    sections = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        sections[snum] = sorted(
            (name, tuple((round(x, 6), round(y, 6)) for x, y in trace.points))
            for name, contour in section.contours.items()
            for trace in contour
        )
    return {
        "sections": sections,
        "comment": series.getAttr("kill_test", "comment"),
    }


def history(series):
    """The series history the next save writes: the file's, then this session's.

    Each line without its date and time, which differ from run to run.
    """
    log_fp = os.path.join(series.hidden_dir, "existing_log.csv")
    text = ""
    if os.path.isfile(log_fp):
        with open(log_fp, encoding="utf-8") as f:
            text = f.read()
    text += "\n" + str(series.log_set)
    return [", ".join(line.split(", ")[2:]) for line in text.splitlines() if line.strip()]


def check_history(got, old, expect):
    """Nothing the file already had is gone, and a save's own entries are there."""
    assert got[:len(old)] == old, "the series history lost entries"
    if expect != "old":
        assert any("kill_test" in line for line in got[len(old):]), got


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
    """Decline the unsaved work, open the .jser, and close it again."""
    clear_hidden(folder)
    series = open_series(os.path.join(folder, f"{NAME}.jser"))
    try:
        return content(series), history(series)
    finally:
        series.close()


def has_working_series(folder):
    """Whether the window would offer the working folder as unsaved work."""
    hidden = hidden_dir(folder)
    return os.path.isdir(hidden) and any(f.endswith(".ser") for f in os.listdir(hidden))


@pytest.fixture(scope="module")
def states(tmp_path_factory):
    """The series before the save, after it, and after it minus the current section.

    Also the history the file had before the save, under "old-history".
    """
    base = tmp_path_factory.mktemp("save-kill-states")

    old_dir = base / "old"
    old_dir.mkdir()
    shutil.copyfile(FIXTURE, old_dir / f"{NAME}.jser")
    old, old_history = open_jser_only(str(old_dir))

    new_dir = base / "new"
    new_dir.mkdir()
    shutil.copyfile(FIXTURE, new_dir / f"{NAME}.jser")
    run_child(str(new_dir / f"{NAME}.jser"), "none")
    new, new_history = open_jser_only(str(new_dir))

    # the edits are all there, so "old" and "new" can be told apart per section
    for snum in (0, 2, 3, 4):
        assert any(name == "kill_test" for name, _ in new["sections"][snum]), snum
        assert new["sections"][snum] != old["sections"][snum], snum
    assert new["sections"][1] == old["sections"][1]
    assert new["comment"] == "edited before the save" != old["comment"]
    assert old_history
    check_history(new_history, old_history, "new")

    pre_current = dict(new, sections={**new["sections"], 3: old["sections"][3]})
    return {"old": old, "new": new, "pre-current": pre_current, "old-history": old_history}


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
    got, got_history = open_jser_only(str(declined))
    if expect == "old":
        assert untouched, "the .jser was written before the save finished"
    assert got == states[expect], f"the .jser does not hold the {expect} series"
    check_history(got_history, states["old-history"], expect)
    leftovers = [
        f for f in os.listdir(declined)
        if f != f"{NAME}.jser" and f != f".{NAME}"
    ]
    # a temp file left by the killed save is one a later open removes
    assert all(TEMP_NAME.fullmatch(f) for f in leftovers), leftovers


def check_working_folder(folder, expect, states, tmp_path):
    """Open the unsaved work: it holds every edit, and a save from it keeps them."""
    accepted = tmp_path / "accepted"
    shutil.copytree(folder, accepted)
    if expect == "gone-or-new" and not has_working_series(str(accepted)):
        return  # nothing to offer: the window clears the folder and opens the .jser
    assert has_working_series(str(accepted)), "the working folder is not offered"
    want = states["new" if expect == "gone-or-new" else expect]

    series = open_series(str(accepted / f"{NAME}.jser"))
    try:
        assert content(series) == want, "the working folder lost work"
        check_history(history(series), states["old-history"], "new")
        series.saveJser()
    finally:
        series.close()
    got, got_history = open_jser_only(str(accepted))
    assert got == want, "a save from the working folder lost work"
    check_history(got_history, states["old-history"], "new")


@pytest.mark.parametrize("point", [
    pytest.param(point, marks=pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=f"Save and close killed while the working folder is removed: {CLOSE_REMOVE_ISSUE}",
    )) if point == "close-remove" else point
    for point in POINTS
])
def test_kill_during_save_then_reopen(tmp_path, states, point):
    jser_expect, hidden_expect = POINTS[point]
    folder, untouched = kill_at(tmp_path, point)
    check_jser(folder, untouched, jser_expect, states, tmp_path)
    check_working_folder(folder, hidden_expect, states, tmp_path)

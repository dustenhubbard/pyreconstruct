"""Save As keeps the loaded sections and the series file on their own paths.

`Series.move` renames the files on disk by swapping only the series-name
prefix (`renamedSeriesFile`), but it used a plain `str.replace` on the paths
it keeps in memory. When the old name's text also appeared in the section
number or the extension, those paths pointed somewhere else:

- a series named "1" saved as "2.jser" sent section 11 to `2.22`, so the next
  save overwrote section 22 with section 11;
- a series named "s" saved as "x.jser" pointed the series file at `x.xer`,
  so the next save left a stray file next to the real `x.ser`.
"""

import os

import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.trace import Trace


SECTION_COUNT = 25


def make_series(root, name):
    """A saved series with one distinct (empty) image per section."""
    imgdir = os.path.join(root, "imgs")
    os.makedirs(imgdir)
    imgs = []
    for i in range(SECTION_COUNT):
        fp = os.path.join(imgdir, f"img{i:02d}.tif")
        open(fp, "wb").close()
        imgs.append(fp)

    series = Series.new(imgs, name, 0.00254, 0.05)
    series.jser_fp = os.path.join(root, f"{name}.jser")
    series.saveJser()
    series.close()

    return Series.openJser(os.path.join(root, f"{name}.jser"))


def mark(section, name):
    trace = Trace(name, (255, 0, 0))
    trace.points = [(1, 1), (2, 1), (2, 2), (1, 2)]
    trace.closed = True
    section.addTrace(trace)


# (old name, new name): numeric names whose text sits inside section numbers,
# one-letter names, and names that are part of the ".ser" extension
NAMES = [
    ("1", "2"),
    ("12", "3"),
    ("s", "x"),
    ("r", "q"),
    ("se", "ab"),
    ("ser", "abc"),
]


@pytest.mark.parametrize("old, new", NAMES)
def test_save_as_keeps_every_path_on_its_own_file(tmp_path, old, new):
    series = make_series(str(tmp_path), old)
    try:
        section = series.loadSection(11)
        b_section = series.loadSection(12)

        series.move(os.path.join(str(tmp_path), f"{new}.jser"), section, b_section)

        hidden = series.hidden_dir
        assert os.path.basename(series.filepath) == f"{new}.ser"
        assert os.path.isfile(series.filepath)
        assert section.filepath == os.path.join(hidden, series.sections[11])
        assert b_section.filepath == os.path.join(hidden, series.sections[12])
        assert os.path.basename(section.filepath) == f"{new}.11"
        assert os.path.basename(b_section.filepath) == f"{new}.12"

        before = sorted(os.listdir(hidden))
        mark(section, "MARK_11")
        section.save()
        b_section.save()
        series.save()
        assert sorted(os.listdir(hidden)) == before, "a save wrote a stray file"

        series.saveJser()
    finally:
        series.close()

    reopened = Series.openJser(os.path.join(str(tmp_path), f"{new}.jser"))
    try:
        def names(n):
            return {t.name for t in reopened.loadSection(n).tracesAsList()}

        assert "MARK_11" in names(11)
        for n in range(SECTION_COUNT):
            if n != 11:
                assert "MARK_11" not in names(n), f"section {n} got section 11's trace"
            assert reopened.loadSection(n).src == f"img{n:02d}.tif"
    finally:
        reopened.close()


def test_save_as_with_only_one_section_loaded(tmp_path):
    """The field alone, no second section: the edit still lands on section 11."""
    series = make_series(str(tmp_path), "1")
    try:
        section = series.loadSection(11)
        series.move(os.path.join(str(tmp_path), "2.jser"), section, None)
        mark(section, "MARK_11")
        section.save()
        series.save()
        series.saveJser()
    finally:
        series.close()

    reopened = Series.openJser(os.path.join(str(tmp_path), "2.jser"))
    try:
        s11 = reopened.loadSection(11)
        s22 = reopened.loadSection(22)
        assert "MARK_11" in {t.name for t in s11.tracesAsList()}
        assert s22.src == "img22.tif"
        assert "MARK_11" not in {t.name for t in s22.tracesAsList()}
    finally:
        reopened.close()

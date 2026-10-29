"""A section file read for the series data, with no `Section` built.

A series open (first open and resume) used to build every section through
`Section.__init__` only to hand it to `SeriesData.updateSection` and drop it.
The series data needs much less: the decoded rows after `Section.updateJSON`,
the transforms, flags and a few scalars. `SectionRows` holds just that, and
`SeriesData.addOpenedSection` measures its rows into the same numbers.

The trace ids are registered as `Section.__init__` registers them
(`Section.issueLoadedTraceIDs`, same inputs, same order), so the issuer ends
the open in the same state, and a later `Series.loadSection` of an unchanged
file gets the same ids back.

A section with any row that `Trace.fromList` or the columnar store reads in
its own way (`plainCoordinates`) is built as a `Section`, as before. That is
decided before the issuer is touched, so each section's ids are registered
once, by one path.
"""

from typing import Optional, Union

from PyReconstruct.modules.constants import fast_loads

from .columnar_store import coordinatesFromRow
from .flag import Flag
from .section import Section, TransformsDict
from .trace import normalizeObjectName
from .transform import Transform


class SectionRows():
    """The parts of a section file the series data reads, after `updateJSON`.

    Carries the attribute names `SeriesData.updateSection` reads off a
    `Section` for the section's entry (thickness, calgrid, align_locked,
    bc_profiles, src, mag, flags, tforms), built the way `Section.__init__`
    builds them.
    """

    def __init__(self, n : int, section_data : dict, coordinates : dict):
        """
            Params:
                n (int): the section number
                section_data (dict): the decoded file after `updateJSON`
                coordinates (dict): name -> one (n, 2) array per row
                    (`plainCoordinates`)
        """
        self.n = n
        self.src = Section.imageName(section_data["src"])
        self.bc_profiles = section_data["brightness_contrast_profiles"]
        self.mag = section_data["mag"]
        self.align_locked = section_data["align_locked"]
        self.tforms = TransformsDict()
        for a in section_data["tforms"]:
            self.tforms[a] = Transform(section_data["tforms"][a])
        self.thickness = section_data["thickness"]
        ## name -> rows, in the file's (sorted) order
        self.contours = section_data["contours"]
        self.coordinates = coordinates
        self.flags = [Flag.fromList(l, n) for l in section_data["flags"]]
        self.calgrid = section_data["calgrid"]


def plainCoordinates(contours : dict) -> Optional[dict]:
    """Each row's points as an (n, 2) array, or None if any row is not plain.

    A plain row is one whose numbers in the series data do not depend on how
    `Trace.fromList` and the columnar store read it, so reading the row's
    fields directly gives the same values:

      * its contour name is already normalized (`Trace.fromList` strips it
        and the store normalizes it; `SeriesData._storeRows` then adds those
        traces one at a time under the new name);
      * it has 8 fields (a 9-field row names its own trace);
      * `coordinatesFromRow` reads its x and y, with more than one point
        (`Section.__init__` drops a shorter row);
      * its color is three ints from 0 to 255 (the store keeps `uint8`);
      * its fill mode is a list of strings and its tags a list.

        Params:
            contours (dict): name -> rows, after `updateJSON`
        Returns:
            (dict): name -> list of arrays, or None
    """
    coordinates = {}
    for name, rows in contours.items():
        if name != normalizeObjectName(name):
            return None
        arrays = []
        for row in rows:
            if type(row) is not list or len(row) != 8:
                return None
            x, y, color, _, _, _, fill_mode, tags = row
            array = coordinatesFromRow(x, y)
            if array is None or len(array) < 2:
                return None
            if type(color) is not list or len(color) != 3:
                return None
            for c in color:
                if type(c) is not int or not 0 <= c <= 255:
                    return None
            if type(fill_mode) is not list or any(type(m) is not str for m in fill_mode):
                return None
            if type(tags) is not list:
                return None
            arrays.append(array)
        coordinates[name] = arrays
    return coordinates


def readSectionRows(n : int, series) -> Optional[SectionRows]:
    """Read a section file and register its trace ids, as `Section.__init__`
    does, or return None (and touch nothing) if a row is not plain.

        Params:
            n (int): the section number
            series (Series): the series
    """
    # hidden trace file, filled first if it is a stub (lazy_sections.py)
    with open(series.presentSection(n), "rb") as f:
        raw = f.read()
    section_data = fast_loads(raw)
    stored_ids = {}
    Section.updateJSON(section_data, n, stored_ids=stored_ids)
    coordinates = plainCoordinates(section_data["contours"])
    if coordinates is None:
        return None
    Section.issueLoadedTraceIDs(n, series, raw, section_data["contours"], stored_ids)
    return SectionRows(n, section_data, coordinates)


def loadForOpen(series, n : int) -> Union[SectionRows, Section]:
    """A section as a series open reads it: its rows, or the `Section` when a
    row is not plain (`readSectionRows`)."""
    rows = readSectionRows(n, series)
    if rows is None:
        return series.loadSection(n)
    return rows

import os
import json
from typing import Dict, List, Union

from .contour import Contour
from .filters import passesFilters
from .trace import Trace, normalizeObjectName
from .flag import Flag
from .transform import Transform
from .log import LogSetPair

from PyReconstruct.modules.calc import (
    getDistanceFromTrace,
    distance,
    getImgDims
)

from PyReconstruct.modules.constants import (
    fast_loads,
    fast_dumps,
    canon_keys_inplace,
    SECTION_KEYS
)

from PyReconstruct.modules.backend.exports import export_svg, export_png


## --- the test-only columnar dual-write gate ---------------------------------
##
## Slice 3 of the Phase 1 rewiring. A `Section` can carry a `SectionColumns`
## beside its own `self.contours` and mirror every mutation into it, so that the
## columnar store gets driven by real code on real data -- and checked against
## the object model after every single mutation -- before one call site anywhere
## is flipped to *read* from it. Nothing reads the store. `Section` is the only
## class in the tree that knows any of this exists.
##
## THIS IS A TEST HARNESS, NOT A FEATURE, AND THE GATE IS BUILT SO THAT A REAL
## USER SESSION CANNOT REACH IT.
##
## `PYRECON_TEST_ONLY_COLUMNAR_DUAL_WRITE=1` in the process environment is the
## only thing that turns it on. Specifically:
##
##   * **Nothing in `PyReconstruct/` sets it, reads it, or names it** other than
##     the one constant below and the one `os.environ.get` it feeds.
##     `tests/test_section_columnar_dual_write.py::test_nothing_in_the_shipped_
##     package_can_turn_the_gate_on` walks the whole package and fails the moment
##     that stops being true.
##   * **It is not a setting.** Not a series option, not a QSettings key, not a
##     command-line flag, not reachable from any dialog, so no sequence of clicks
##     in a normal `uv run PyReconstruct` launch can produce it. There is
##     deliberately no default-off-but-reachable toggle: the gate has to be put
##     into the environment before the process starts, by something outside the
##     application, which in practice means a test's `monkeypatch.setenv`.
##   * **The spelling is `== "1"` exactly**, the rule `PYRECON_UNATTENDED`,
##     `PYRECON_FORCE_FROZEN` and `PYRECON_JSER_PRETTY` already use, so a stale
##     `...=0` left in a shell profile is off rather than a third state.
##
## With the gate unset -- which is every shipped launch -- `self._columns` is
## `None`, every hook below returns on its first line, no store is built, no
## memory is doubled and no assertion runs.
##
## The cost with the gate ON is deliberately not optimized: the consistency
## check materializes the *whole* section and compares it field by field after
## every mutation, which is O(section) per mutation. That is the wrong trade for
## production and the right one for a harness whose only job is to catch
## divergence as close to its cause as it can.
DUAL_WRITE_ENV_VAR = "PYRECON_TEST_ONLY_COLUMNAR_DUAL_WRITE"


def dualWriteRequested() -> bool:
    """True when the test-only columnar dual-write gate is set to exactly "1".

    Read at `Section.__init__` time, per section, rather than cached at import:
    a test can turn the gate on and load a section and get a store, and the next
    test can turn it off and load a section and get nothing, with no import-order
    dependency between them.
    """
    return os.environ.get(DUAL_WRITE_ENV_VAR) == "1"


class ColumnarDualWriteMismatch(AssertionError):
    """The columnar store and the object model disagree after a mutation.

    Raised, never logged and never swallowed. Catching store/object divergence
    is the entire purpose of the dual-write slice: a mismatch a test run
    survives is a mismatch that teaches nothing, and every later slice of the
    rewiring rests on the claim that the two representations agree.
    """


def _traceDifferences(stored : Trace, obj : Trace) -> list:
    """Every field on which a materialized row differs from a real trace.

    Compared against the **in-memory** trace, never against `getList()`: the
    store holds unrounded float64 while `getList` rounds to 7 decimal places, so
    a comparison through serialization is two lossy things agreeing and proves
    nothing about either. See the `columnar_store` module docstring, which puts
    the store on the unrounded side of that rounding on purpose.

    Container *types* are normalized on both sides before comparing, because
    they legitimately differ and a difference there is not a divergence: a
    file-loaded trace's `color` and `fill_mode` are `list`s while one built in
    memory carries `tuple`s, and the store's readers hand back `list`s by
    design.

        Params:
            stored (Trace): the trace `SectionColumns.materializeTrace` rebuilt
            obj (Trace): the trace the object model actually holds
        Returns:
            (list): one human-readable string per differing field; empty when
                the row and the trace agree
    """
    differences = []

    if stored.name != obj.name:
        differences.append(f"name: store {stored.name!r} != object {obj.name!r}")

    stored_points = [(float(x), float(y)) for x, y in stored.points]
    object_points = [(float(x), float(y)) for x, y in obj.points]
    if stored_points != object_points:
        if len(stored_points) != len(object_points):
            differences.append(
                f"points: store holds {len(stored_points)}, object holds "
                f"{len(object_points)}"
            )
        else:
            ## The first divergent point rather than both whole lists: a real
            ## trace runs to hundreds of points and dumping two of them buries
            ## the one pair that actually differs.
            for i, (s, o) in enumerate(zip(stored_points, object_points)):
                if s != o:
                    differences.append(f"points[{i}]: store {s!r} != object {o!r}")
                    break

    if list(stored.color) != list(obj.color):
        differences.append(
            f"color: store {list(stored.color)!r} != object {list(obj.color)!r}"
        )

    for attribute in ("closed", "negative", "hidden"):
        stored_flag = bool(getattr(stored, attribute))
        object_flag = bool(getattr(obj, attribute))
        if stored_flag != object_flag:
            differences.append(
                f"{attribute}: store {stored_flag!r} != object {object_flag!r}"
            )

    if list(stored.fill_mode) != list(obj.fill_mode):
        differences.append(
            f"fill_mode: store {list(stored.fill_mode)!r} != object "
            f"{list(obj.fill_mode)!r}"
        )

    if set(stored.tags) != set(obj.tags):
        differences.append(
            f"tags: store {sorted(stored.tags, key=str)!r} != object "
            f"{sorted(obj.tags, key=str)!r}"
        )

    return differences


def tracesWithoutCounterpart(donor : Contour, keeper : Contour) -> list:
    """Return the traces in donor that overlap nothing at all in keeper.

    This is the distinction an import needs before it discards a contour. A
    donor trace that overlaps a keeper trace -- at any ratio, however small --
    is plausibly an earlier or a later version of it, so resolving the two in
    the keeper's favour is a merge decision. A donor trace that overlaps
    *nothing* on the keeper side is not a version of anything there: it is
    independent annotation work, and discarding it destroys a trace a human drew
    and cannot get back.

    **``open_curve=False`` keeps this site on the area comparison, deliberately,
    so that the open-trace curve metric changes nothing here.** ``threshold=0``
    asks a categorically different question from the threshold the import dialog
    asks: "do these two traces overlap at all", not "are these two traces the same
    trace". The curve metric was designed and measured for the second one. On the
    import merge at 0.95 it is measured clean on real data -- 264 of 264 genuine
    duplicate open pairs detected, 0 different-structure collapses at every
    threshold the slider can reach. At ``threshold=0`` it was neither, and the
    predicate there reduces to ``r > 0``, which accepts any positive ratio at all:

      * Two open traces that merely cross or touch score a small positive ratio
        (0.0064 for a T junction), about the tolerance over the shorter arc
        length. Bounding the tolerance shrinks that number and cannot zero it; no
        coverage measure taken at a positive tolerance can.
      * On the reporting user's series that turned 487 of 979 donor open traces
        from orphans into counterparts, and an orphan is what makes the history
        shortcut in Section.importTraces back off. 618 of the 664 newly matched
        pairs were her fiducial and calibration marks (``SF1_Wh``, ``grid``,
        ``Wh*_Dim``), whose members genuinely intersect -- their mean deviation is
        1,118 px but their closest approach is 0.67 px at the median, and a
        tolerance tests the closest approach. **46 were biological objects across
        22 contours**, and losing orphan status is what lets the shortcut discard a
        whole donor contour with no flag and no log entry, so those 46 were a
        silent-loss risk.

    So the metric goes where it was validated and nowhere else. The alternatives
    considered were a positive floor on the ratio at this site, and a minimum
    contact length below which the curve metric reports 0; both are new rules
    invented for an untested question, where preserving the existing answer is a
    rule that already has years of use behind it. If the meaning of "overlaps at
    all" for a curve is ever worth revisiting, it should be revisited on its own
    evidence rather than inherited as a side effect of fixing duplicate detection.

    Note the area comparison is not a good answer to this question either -- it
    reports a pair of open traces whose closing chords cross as overlapping even
    when the curves run 49 px apart, which is a silent loss of its own. It is
    simply the answer this call site has always given, and the one the open-curve
    change is not entitled to alter.

        Params:
            donor (Contour): the contour whose traces are at risk
            keeper (Contour): the contour that would survive
        Returns:
            (list): the donor traces with no counterpart in keeper
    """
    if not len(donor):
        return []
    if not len(keeper):
        return donor.getTraces()  # nothing to overlap: all of it is independent

    return [
        d_trace for d_trace in donor
        if not any(
            d_trace.overlaps(k_trace, threshold=0, open_curve=False)
            for k_trace in keeper
        )
    ]


class Section():

    ## Class-level defaults for the test-only dual-write harness. `__init__`
    ## assigns instance attributes over both, so these exist for one case: a
    ## `Section` built through `Section.__new__` without running `__init__`,
    ## which a dozen test modules do to drive one method against a handful of
    ## hand-set attributes. Without these, adding a hook to a mutator would
    ## break every one of them -- which is the opposite of invisible.
    ##
    ## The shared dict is never written. Every path that puts a row into it
    ## runs only when `_columns is not None`, and the only thing that sets
    ## `_columns` is `resyncColumnarStore`, which rebinds an instance dict
    ## first.
    _columns = None
    _column_rows : dict = {}

    def __init__(self, n : int, series):
        """Load the section file.
        
            Params:
                n (int): the section number
                series (Series): the series that contains the section
        """
        self.n = n
        self.series = series

        ## The test-only columnar dual-write harness. Declared here, before
        ## anything can fail, so that `self._columns is None` is true of a
        ## half-constructed Section as well as of every shipped one. See
        ## DUAL_WRITE_ENV_VAR above: `None` is what a normal launch gets, and it
        ## makes every hook on this class a one-line return.
        self._columns = None
        self._column_rows : dict = {}

        self.filepath = os.path.join(  # hidden trace file
            self.series.getwdir(),
            self.series.sections[n]
        )

        self.selected_traces : list[Trace] = []
        self.selected_ztraces = []
        self.selected_flags = []

        self.temp_hide = []          # traces to temp hide
        self.traces_group_hide = []  # traces to hide by group viz

        with open(self.filepath, "rb") as f:
            section_data = fast_loads(f.read())
        
        Section.updateJSON(section_data, n)  # update any missing attributes

        self.src = os.path.basename(section_data["src"])
        self.bc_profiles = section_data["brightness_contrast_profiles"]
        self.mag = section_data["mag"]
        self.align_locked = section_data["align_locked"]

        self.tforms = TransformsDict()
        
        for a in section_data["tforms"]:
            self.tforms[a] = Transform(section_data["tforms"][a])
        
        self.thickness = section_data["thickness"]
        self.contours : dict[str, Contour] = {}

        for name in section_data["contours"]:
            
            trace_list = []
            
            for trace_data in section_data["contours"][name]:
                trace = Trace.fromList(trace_data, name)
                # screen for defective traces. `updateJSON` above now applies
                # both screens to the stored data as well, so on this path the
                # two lines below are a no-op; they are kept because callers
                # that build a Section from data that has not been through
                # `updateJSON` still need them, and because the in-memory value
                # is the one the rest of the program reads.
                l = len(trace.points)
                if l == 2:
                    trace.closed = False
                if l > 1:
                    trace_list.append(trace)
                    
            self.contours[name] = Contour(
                name,
                trace_list
            )
        
        ## Build the parallel store, if and only if the test-only gate is set.
        if dualWriteRequested():
            self.resyncColumnarStore()

        self.flags = [Flag.fromList(l, self.n) for l in section_data["flags"]]

        self.calgrid = section_data["calgrid"]

        ## Modify temp_hide based on group visibility
        self.setGroupVisibility(series.groups_visibility)
        
        ## For GUI use
        self.clearTracking()
    
    @property
    def tform(self):
        return self.tforms[self.series.alignment]
    @tform.setter
    def tform(self, new_tform):
        if self.series.alignment != "no-alignment":
            self.tforms[self.series.alignment] = new_tform
            self._dualWriteTransformChange()  # test-only

    @property
    def brightness(self):
        return self.bc_profiles[self.series.bc_profile][0]
    @brightness.setter
    def brightness(self, b):
        c = self.contrast
        self.bc_profiles[self.series.bc_profile] = (b, c)
    
    @property
    def contrast(self):
        return self.bc_profiles[self.series.bc_profile][1]
    @contrast.setter
    def contrast(self, c):
        b = self.brightness
        self.bc_profiles[self.series.bc_profile] = (b, c)
    
    @property
    def src_fp(self):
        if self.series.src_dir.endswith("zarr"):
            scales = self.zarr_scales
            return os.path.join(
                self.series.src_dir,
                f"scale_{min(scales)}",
                self.src
            )
        else:
            return os.path.join(
                self.series.src_dir,
                self.src
            )

    @property
    def img_dims(self):
        return getImgDims(self.src_fp)
    
    @property
    def zarr_scales(self):
        if self.series.src_dir.endswith("zarr"):
            return [
                int(s.split("_")[1])
                for s in os.listdir(self.series.src_dir)
                if (
                    s.startswith("scale_") and 
                    s.split("_")[1].isnumeric() and 
                    self.src in os.listdir(os.path.join(self.series.src_dir, s))
                )
            ]

    @staticmethod
    def updateJSON(section_data, n):
        """Add missing attributes to section JSON.

        (Updates the dictionary in place)

            Params:
                section_data (dict): the JSON data to update
                n (int): the section number
            Returns:
                (dict): the contour renames this call performed, old name -> new
                    name. Empty for a section whose names already satisfy
                    ``normalizeObjectName``, which is every section written by a
                    build that has the rule. The caller needs this because the
                    rename is only half done here: a series keeps an object's
                    groups, comment, curation, user columns and hosts under the
                    object *name*, in the series file, which this function does
                    not see. ``Series.openJser`` repoints them.
        """
        renamed = {}

        # Recorded BEFORE the back-fill loop below inserts the key, because the
        # legacy brightness/contrast migration needs to know whether the *file*
        # carried a profiles dict -- a fact that is unrecoverable once the
        # default has been back-filled.
        had_bc_profiles = isinstance(
            section_data.get("brightness_contrast_profiles"), dict
        )

        empty_section = Section.getEmptyDict()
        for key in empty_section:
            if key not in section_data:
                section_data[key] = empty_section[key]

        # modify brightness/contrast
        if "brightness" in section_data and "contrast" in section_data:
            # fix exact numbers from an older version
            if abs(section_data["brightness"]) > 100:
                section_data["brightness"] = 0
            section_data["contrast"] = int(section_data["contrast"])

            # Move into profiles by MERGING. This used to assign a fresh
            # single-key dict, which discarded every other named profile the
            # section had. getDict() never writes the legacy scalars back, so
            # they vanish on the first save -- meaning the migration ran on
            # every open until that save, and the save then made the loss of
            # the other profiles permanent.
            profiles = section_data["brightness_contrast_profiles"]
            if not isinstance(profiles, dict):
                # Not mergeable, and would fail on load. Treat it as absent,
                # which is what the old wholesale assignment did in effect.
                profiles = {}
                section_data["brightness_contrast_profiles"] = profiles
                had_bc_profiles = False

            # Whether the scalars override an existing "default" is decided by
            # whether the file carried a profiles dict at all -- NOT by
            # comparing values, which cannot tell a deliberate (0, 0) default
            # from the back-filled placeholder:
            #   no profiles key  -> a pre-profiles file; the scalars ARE its
            #                       only brightness/contrast, so they become
            #                       "default"
            #   profiles present -> already profiles-aware, so that dict is
            #                       authoritative. It is what the profiles UI
            #                       has been showing and editing, while the
            #                       scalars are a stale leftover of an older
            #                       schema. Nothing is overwritten.
            if not had_bc_profiles or "default" not in profiles:
                profiles["default"] = (
                    section_data["brightness"], section_data["contrast"]
                )

        # scan contours
        flagged_contours = []
        for cname in section_data["contours"]:
            flagged_traces = []
            for i, trace in enumerate(section_data["contours"][cname]):
                # convert trace to list format if needed
                if type(trace) is dict:
                    trace = [
                        trace["x"],
                        trace["y"],
                        trace["color"],
                        trace["closed"],
                        trace["negative"],
                        trace["hidden"],
                        trace["mode"],
                        trace["tags"]
                    ]
                    section_data["contours"][cname][i] = trace
                # remove history from trace if it exists
                elif len(trace) == 9:
                    trace.pop()
                # check for trace mode
                if type(trace[6]) is not list:
                    trace[6] = ["none", "none"]
                # canonical tag order. Trace.getList sorts tags, but that only
                # runs for a section that goes back through the model: saveJser
                # reads the hidden dir verbatim, so a section the user never
                # touched kept whatever order its source file had and the
                # writer's "tags are sorted" guarantee did not hold for it.
                if type(trace[7]) is list and len(trace[7]) > 1:
                    trace[7] = sorted(trace[7], key=str)
                # check for empty/defective traces
                if len(trace[0]) < 2:
                    flagged_traces.append(i)
                # Two points enclose no area, so every reader forces such a
                # trace open in memory (`Section.__init__` below, the undo
                # baseline in `state_manager.getContours`, and `addTrace`).
                # Correct the stored flag as well, for the same reason the tag
                # sort above lives here: `saveJser` copies the hidden dir
                # verbatim, so the in-memory coercion reached the file only for
                # sections the user happened to open AND save. That is the
                # worst of the three possible behaviors -- the flag flipped
                # from true to false at some unpredictable later save rather
                # than never, so byte-diffing a .jser showed a change no edit
                # accounts for. Doing it here makes the correction happen once,
                # on unpack, for every section alike.
                #
                # The divergent row is not hypothetical and does not require a
                # hand-edited file: a Reconstruct XML import writes
                # `trace.getList()` straight into the section file with no
                # arity check (`xml_json_conversions.py`), so a two-point
                # closed contour keeps `closed: true` across the import.
                elif len(trace[0]) == 2:
                    trace[3] = False
            # remove the flagged defective traces
            for i in sorted(flagged_traces, reverse=True):
                section_data["contours"][cname].pop(i)
            # check if the contour is empty
            if not section_data["contours"][cname]:
                flagged_contours.append(cname)
        # remove flagged contours
        for cname in flagged_contours:
            del(section_data["contours"][cname])
        
        # remove no-alignment if present
        if "no-alignment" in section_data["tforms"]:
            del(section_data["tforms"]["no-alignment"])
        
        # iterate through flags and add resolved status or section number and ID.
        # The ID is DERIVED from the flag's own content, not generated: this
        # migration runs on every unpack of a .jser whose flags predate the ID
        # field, and a random ID there gave the same flag a different identity
        # on every open. Flag.equals compares IDs and nothing else, so
        # Series.importFlags deduplicated on an identity that did not survive
        # the trip and duplicated every legacy flag it was asked to merge.
        # See Flag.deriveID.
        taken = set(
            flag[0] for flag in section_data["flags"]
            if len(flag) == 7 and isinstance(flag[0], str)
        )
        for flag in section_data["flags"]:
            if len(flag) == 5:
                flag.append(False)
            if len(flag) == 6:
                id = Flag.deriveID([n] + flag, taken)
                taken.add(id)
                flag.insert(0, id)

        # iterate through contours and remove whitespace
        for cname in tuple(section_data["contours"].keys()):

            ## print(f"'{cname}'")
            updated_cname = normalizeObjectName(cname)

            if cname != updated_cname:

                if updated_cname not in section_data["contours"]:
                    section_data["contours"][updated_cname] = []

                section_data["contours"][updated_cname] += section_data["contours"][cname]

                del(section_data["contours"][cname])

                renamed[cname] = updated_cname

        # Canonical key order. The back-fill loop at the top of this function
        # appends any missing key at the tail, so two sections with identical
        # content but different provenance differed byte-wise. Rebuild in the
        # writer's order; keys this build has no concept of (e.g. the legacy
        # scalar brightness/contrast pair) are preserved, sorted, after the
        # documented nine. Rebuilt in place: the caller holds this dict.
        canon_keys_inplace(section_data, SECTION_KEYS)

        # Canonical contour order, so an object added later in a session lands in
        # the same place as one that was there from the start.
        contours = section_data["contours"]
        if isinstance(contours, dict) and list(contours) != sorted(contours, key=str):
            ordered = {name: contours[name] for name in sorted(contours, key=str)}
            contours.clear()
            contours.update(ordered)

        return renamed

    def getDict(self) -> dict:
        """Convert section object into a dictionary.
        
            Returns:
                (dict) all of the compiled section data
        """
        d = {}
        d["src"] = self.src
        d["brightness_contrast_profiles"] = self.bc_profiles
        d["mag"] = self.mag
        d["align_locked"] = self.align_locked

        # save tforms
        d["tforms"] = {}
        for a in self.tforms:
            if a != "no-alignment":  # not needed to save the no-alignment option
                d["tforms"][a] = self.tforms[a].getList()

        d["thickness"] = self.thickness

        # save contours (sorted: canonical ordering)
        d["contours"] = {}
        for contour_name in sorted(self.contours, key=str):
            if not self.contours[contour_name].isEmpty():
                d["contours"][contour_name] = [
                    trace.getList(include_name=False) for trace in self.contours[contour_name]
                ]
        
        d["flags"] = [f.getList() for f in self.flags]

        d["calgrid"] = self.calgrid

        return d
    
    @staticmethod
    def getEmptyDict() -> dict:
        """Returns a dict representing an empty section."""
        section_data = {}
        section_data["src"] = ""  # image location
        section_data["brightness_contrast_profiles"] = {
            "default": (0, 0)
        }
        section_data["mag"] = 0.00254  # microns per pixel
        section_data["align_locked"] = True
        section_data["thickness"] = 0.05  # section thickness
        section_data["tforms"] = {}  
        section_data["tforms"]["default"]= Transform.identity().getList() # identity matrix default
        section_data["contours"] = {}
        section_data["flags"] = []
        section_data["calgrid"] = False

        return section_data
    
    @staticmethod
    def new(series_name : str, snum : int, image_location : str, mag : float, thickness : float, wdir : str):
        """Create a new blank section file.
        
            Params:
                series_name (str): the name for the series
                snum (int): the section number
                image_location (str): the file path for the image
                mag (float): microns per pixel for the section
                thickness (float): the section thickness in microns
                wdir (str): the working directory for the sections
            Returns:
                (Section): the newly created section object
        """
        section_data = Section.getEmptyDict()
        section_data["src"] = os.path.basename(image_location)  # image location
        section_data["mag"] = mag  # microns per pixel
        section_data["thickness"] = thickness  # section thickness

        section_fp = os.path.join(wdir, series_name + "." + str(snum))
        with open(section_fp, "w") as section_file:
            section_file.write(json.dumps(section_data, indent=2))
   
    def save(self, update_series_data=True):
        """Save file into json.
        
            Params:
                update_series_data (bool): True if series data object should be updated
        """
        if self.series.isWelcomeSeries():
            return

        # A section the series no longer has is not written back. self.filepath
        # was resolved from series.sections at construction, so a Section object
        # outlives its entry in the index and keeps pointing at the file that
        # deleteSections removed: the field holds the deleted section in
        # b_section (changeSection -> swapABsections), and MainWindow.saveAllData
        # saves b_section on every save, recreateTables included, which put the
        # file straight back and resurrected the section on the next open. There
        # is nothing to persist for a section that is not part of the series, so
        # this is a no-op and not a refusal.
        if self.n not in self.series.sections:
            return

        # update the series data
        if update_series_data:
            self.series.data.updateSection(self, update_traces=True)
    
        d = self.getDict()
        # write atomically: a crash or ENOSPC mid-write must never leave the
        # section file truncated, so write a sibling temp file and rename it
        # over the original (os.replace is atomic on POSIX/Windows). We do NOT
        # fsync here: this internal working file is re-saved on every section
        # change (mouse-wheel scroll), so fsyncing each scroll would turn the
        # gesture into a synchronous disk flush. The .jser master copy is the
        # durable one; os.replace already prevents a truncated file on crash.
        tmp_fp = self.filepath + ".tmp"
        try:
            with open(tmp_fp, "wb") as f:
                # internal hidden working file -- write compact bytes to cut
                # serialization cost and the bytes re-read on every saveJser
                f.write(fast_dumps(d))
            # a save fires on scroll / section switch; retry a transiently-locked
            # replace (Windows AV/indexer/sync) so it doesn't fail spuriously
            from PyReconstruct.modules.backend.func.atomic_io import replace_with_retry
            replace_with_retry(tmp_fp, self.filepath)
        except OSError:
            # leave the original file untouched; clean up the partial temp
            try:
                os.remove(tmp_fp)
            except OSError:
                pass
            raise
    
    def tracesAsList(self) -> list[Trace]:
        """Return the trace dictionary as a list. Does NOT copy traces.
        
            Returns:
                (list): a list of traces
        """
        trace_list = []
        for contour_name in self.contours:
            for trace in self.contours[contour_name]:
                trace_list.append(trace)
        return trace_list
    
    def setAlignLocked(self, align_locked : bool):
        """Set the alignment locked status of the section.
        
            Params:
                align_locked (bool): the new locked status
        """
        self.align_locked = align_locked
    
    def getAllModifiedNames(self) -> set:
        """Return the names of all the modified traces."""
        trace_names = set([t.name for t in self.added_traces])
        trace_names = trace_names.union(set([t.name for t in self.removed_traces]))
        trace_names = trace_names.union(self.modified_contours)
        return trace_names
    
    def tformsModified(self, scaling_only=False):
        if len(self.tforms_values_copy) != len(self.tforms):
            return True
        for t1, t2 in zip(self.tforms_values_copy, self.tforms.values()):
            if scaling_only:
                if abs(t1.det - t2.det) > 1e-6:
                    return True
            else:
                if not t1.equals(t2):
                    return True
        return False
    
    def clearTracking(self):
        """Clear the added_traces and removed_traces lists."""
        self.added_traces = []
        self.removed_traces = []
        self.modified_contours = set()
        self.tforms_values_copy = [t.copy() for t in self.tforms.values()]
        self.flags_modified = False

    # --- the test-only columnar dual-write harness ---------------------------
    #
    # Every method in this block returns on its first line unless
    # DUAL_WRITE_ENV_VAR was set in the environment before this Section was
    # constructed. Read the module-level comment on that constant first: it is
    # why a shipped launch cannot get here.
    #
    # WHICH MUTATION PATHS ARE MODELLED, AND WHY THERE ARE FEWER HOOKS THAN
    # THIS CLASS HAS MUTATORS
    # -----------------------------------------------------------------------
    # The design proposal named four paths to route: `addTrace`, `removeTrace`,
    # `editTraceAttributes` and `translateTraces`. Reading the class says the
    # last two are not separate paths at all. `editTraceAttributes`,
    # `translateTraces`, `editTraceRadius`, `editTraceShape`, `makeNegative` and
    # `deleteTraces` are each *composed* of `removeTrace` / mutate / `addTrace`,
    # so hooking the two primitives covers all six and hooking them on their own
    # account as well would double-write. That composition is load-bearing for
    # this harness and is pinned by its tests rather than left as a reading.
    #
    # What the two primitives do NOT cover is the mutators that write a trace
    # attribute in place and never leave the contour: `hideTraces`,
    # `hideOtherTraces`, `unhideAllTraces` and `closeTraces` -- one
    # `setAttribute` each -- and `setMag`, which rewrites every trace's
    # coordinates through `Trace.magScale`, one `setCoordinates` each plus a
    # transform change, checked once for the batch because a whole-section
    # rewrite is one mutation. Those get their own hooks. The `tform` setter
    # reports a transform change, which changes no row and only moves the
    # generation counter; the store's own docstring says why that must not be
    # skipped even though nothing this slice does reads the counter.
    #
    # `importTraces` is the one method here that replaces whole contour trace
    # *lists* rather than going through any of the above: `Contour.importTraces`
    # rebinds `self.traces` outright, and the history shortcut swaps one Contour
    # object for another. There is no sequence of per-row mutations to mirror, so
    # the store is rebuilt from the object model at the end of it instead of
    # pretending to have tracked it. That is honest but limited, and the limit is
    # worth stating plainly: the consistency check proves nothing about the
    # inside of an import. Modelling an import as store operations is later work.
    #
    # Paths that replace `Section.contours` from OUTSIDE this class -- the undo
    # restore in `backend/func/state_manager.py`, `Series.deleteObjects`,
    # autoseg's contour deletion -- are deliberately untouched, because this
    # slice is not allowed to change a call site outside `Section`. Something
    # that does that with the gate on has to call `resyncColumnarStore()`
    # afterwards. Nothing in the shipped application does either thing.
    #
    # Forgetting that resync used to fail SILENTLY. It no longer does. An
    # undo restore rebinds `self.contours` to `Contour.copy()` products, which
    # are equal field for field to the traces the store was built from -- so the
    # value comparison in `_assertColumnsMatchObjectModel` saw nothing wrong,
    # while `_column_rows` stayed keyed on the traces that had just been thrown
    # away. The run then died several mutations later on a "holds no row for"
    # naming a trace that was plainly still in its contour. The check now
    # compares the row map's identity domain against the section's live traces
    # as well as the columns' values, so the first hooked mutation after such a
    # rebind names the rebind. That closes the detection gap; it does not make
    # the out-of-class paths safe, and they still owe the resync.

    def resyncColumnarStore(self):
        """Build (or rebuild) the parallel store from the object model.

        Unconditional: the caller decides whether a store is wanted. `__init__`
        calls it once when the gate is set, and the import path calls it through
        `_dualWriteResync`, which is the version that respects the gate.

        The row map is keyed on the `Trace` object itself. `Trace` defines
        neither `__eq__` nor `__hash__`, so that dict is an identity map -- the
        same identity `Contour.remove` already runs on through `list.remove`, so
        the store's notion of "this trace" and the object model's cannot come
        apart. It is a strong reference and it keeps traces alive; that is
        another reason this is not something to ship.
        """
        from .columnar_store import SectionColumns

        self._columns = SectionColumns.fromSection(self)
        self._column_rows = {}

        ## `fromSection` walks `sorted(contours, key=str)` and each contour's
        ## traces in list order, so the rows it appended for a contour line up
        ## one-for-one with that contour's traces. Read back through the store's
        ## public index rather than assuming row numbers, and check the arity, so
        ## that a change in the store's construction order fails here instead of
        ## silently mis-mapping every trace.
        for name in sorted(self.contours, key=str):
            traces = self.contours[name].getTraces()
            rows = self._columns.rowsForContour(name)
            if len(traces) != len(rows):
                raise ColumnarDualWriteMismatch(
                    f"building the store for section {self.n} gave "
                    f"{len(rows)} rows for contour {name!r}, which holds "
                    f"{len(traces)} traces"
                )
            for trace, row in zip(traces, rows):
                self._column_rows[trace] = row

        self._assertColumnsMatchObjectModel("building the store")

    def _dualWriteResync(self):
        """Rebuild the store, if there is one. The gate-respecting form."""
        if self._columns is None:
            return
        self.resyncColumnarStore()

    def _rowFor(self, trace : Trace, operation : str) -> int:
        """The store row mirroring `trace`, or raise saying it has none."""
        row = self._column_rows.get(trace)
        if row is None:
            raise ColumnarDualWriteMismatch(
                f"{operation} on section {self.n} touched a trace the store "
                f"holds no row for: {trace.name!r}, {len(trace.points)} points. "
                f"Either it never entered the section through addTrace, or its "
                f"row has already been retired by removeTrace."
            )
        return row

    def _dualWriteAppend(self, trace : Trace):
        """Mirror an `addTrace` into the store, then check the whole section."""
        if self._columns is None:
            return
        self._column_rows[trace] = self._columns.appendRow(
            name=trace.name,
            points=trace.points,
            color=trace.color,
            closed=trace.closed,
            negative=trace.negative,
            hidden=trace.hidden,
            fill_mode=trace.fill_mode,
            tags=trace.tags,
        )
        self._assertColumnsMatchObjectModel("addTrace")

    def _dualWriteRemove(self, trace : Trace):
        """Mirror a `removeTrace` into the store, then check the whole section."""
        if self._columns is None:
            return
        self._columns.removeRow(self._rowFor(trace, "removeTrace"))
        del self._column_rows[trace]
        self._assertColumnsMatchObjectModel("removeTrace")

    def _dualWriteAttribute(self, trace : Trace, attribute : str, value):
        """Mirror an in-place scalar attribute write into the store."""
        if self._columns is None:
            return
        operation = f"a {attribute} write"
        self._columns.setAttribute(self._rowFor(trace, operation), attribute, value)
        self._assertColumnsMatchObjectModel(operation)

    def _dualWriteAllCoordinates(self, operation : str):
        """Mirror a geometry rewrite that touched every trace on the section.

        One check after the whole batch and not one per trace, which is a
        correctness requirement rather than an optimization: the check compares
        the *whole* section, so a per-trace check inside a whole-section rewrite
        would fire on the traces the batch has not reached yet. A batch mutation
        is one mutation as far as the invariant is concerned.
        """
        if self._columns is None:
            return
        for trace in self.tracesAsList():
            self._columns.setCoordinates(self._rowFor(trace, operation), trace.points)
        self._assertColumnsMatchObjectModel(operation)

    def _dualWriteTransformChange(self):
        """Tell the store the section's alignment moved."""
        if self._columns is None:
            return
        self._columns.noteTransformChange()
        ## No row changes here, so there is nothing new for the check to catch.
        ## Run it anyway: "the generation counter moved and nothing else did" is
        ## exactly the claim, and an unchecked claim is the shape of defect the
        ## store's docstring says the counter exists to prevent.
        self._assertColumnsMatchObjectModel("a transform change")

    def _assertColumnsMatchObjectModel(self, operation : str):
        """Raise unless the store and `self.contours` hold the same thing.

        Reads the store back through `materializeContours`, which exists for
        exactly this comparison and is explicitly not a view, and compares it
        contour by contour, trace by trace, field by field against the object
        model. Every mismatch found is reported, not just the first, because a
        single mutation that went wrong usually goes wrong in more than one
        column and the second one is the informative one.

        **Empty contours are skipped on the object side.** `Section.contours`
        keeps a key whose `Contour` has been emptied -- `removeTrace` never
        deletes the key, and `importTraces` creates empty ones outright --
        while the store's `contourNames()` reports only names with live rows.
        That is the same asymmetry `getDict()` already has, where an empty
        contour is not written to the file, so it is a difference in how the two
        represent nothing rather than a divergence.

            Params:
                operation (str): what was just done, for the message
            Raises:
                ColumnarDualWriteMismatch: on any difference at all
        """
        if self._columns is None:
            return

        materialized = self._columns.materializeContours()
        expected = {
            name: contour.getTraces()
            for name, contour in self.contours.items()
            if not contour.isEmpty()
        }

        complaints = []

        only_store = sorted(set(materialized) - set(expected), key=str)
        if only_store:
            complaints.append(f"contours only in the store: {only_store!r}")
        only_object = sorted(set(expected) - set(materialized), key=str)
        if only_object:
            complaints.append(f"contours only in the object model: {only_object!r}")

        for name in sorted(set(materialized) & set(expected), key=str):
            stored_traces = materialized[name].getTraces()
            object_traces = expected[name]
            if len(stored_traces) != len(object_traces):
                complaints.append(
                    f"contour {name!r}: the store holds {len(stored_traces)} "
                    f"traces, the object model holds {len(object_traces)}"
                )
                continue
            for i, (stored, obj) in enumerate(zip(stored_traces, object_traces)):
                for difference in _traceDifferences(stored, obj):
                    complaints.append(f"contour {name!r} trace {i}: {difference}")

        ## The comparison above reads *values* out of the store, so it is
        ## structurally incapable of seeing a stale row map. A whole-dict rebind
        ## of `self.contours` to equal-valued copies -- which is exactly the
        ## shape of an undo restore -- leaves every field matching and every key
        ## in `_column_rows` pointing at a `Trace` no contour holds any more.
        ## The check passed, and the next `removeTrace` then failed with "holds
        ## no row for" naming a trace that is plainly in the contour. So compare
        ## the map's identity domain too, and the failure lands here, on the
        ## first hooked mutation after the rebind, saying what actually went
        ## wrong instead of surfacing later as a puzzle.
        ##
        ## Identity and not equality, for the same reason the map itself is an
        ## identity map: `Trace` defines no `__eq__`. Sets and not multisets, so
        ## the same `Trace` object appended twice -- which no application path
        ## does -- is left to the arity comparison above rather than newly
        ## rejected here. Both hooks that write the map do so *after* the object
        ## model has already been updated, so this holds at every call site.
        live = {id(trace) for trace in self.tracesAsList()}
        mapped = {id(trace) for trace in self._column_rows}
        if live != mapped:
            complaints.append(
                f"the row map is stale: it holds {len(mapped - live)} trace(s) "
                f"no contour on this section holds any more and is missing "
                f"{len(live - mapped)} that it does. Something replaced this "
                f"section's contours or traces from outside Section without "
                f"calling resyncColumnarStore() afterwards"
            )

        if complaints:
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"{operation} on section {self.n}:\n  " + "\n  ".join(complaints)
            )

    def setMag(self, new_mag : float):
        """Set the magnification for the section.
        
            Params:
                new_mag (float): the new magnification for the section
        """
        # modify the translation component of the transformation
        for tform in self.tforms.values():
            tform.magScale(self.mag, new_mag)
        
        # modify the traces
        for trace in self.tracesAsList():
            trace.magScale(self.mag, new_mag)
        
        # modify the ztraces
        for ztrace in self.series.ztraces.values():
            ztrace.magScale(self.n, self.mag, new_mag)
        
        # modify the flags
        for flag in self.flags:
            flag.magScale(self.mag, new_mag)

        self.mag = new_mag

        # mirror into the test-only store: every trace's geometry was rewritten
        # in place above, and every tform with it
        self._dualWriteAllCoordinates("setMag")
        self._dualWriteTransformChange()

    def addTrace(self, trace : Trace, log_event=True):
        """Add a trace to the trace dictionary.
        
            Params:
                trace (Trace): the trace to add
                log_event (bool): true if the event should be logged
        """        
        # do not add trace if less than two points
        if len(trace.points) < 2:
            return
        # force trace to be open if only two points
        elif len(trace.points) == 2:
            trace.closed = False
        # add to log
        if log_event:
            self.series.addLog(trace.name, self.n, "Create trace(s)")

        if trace.name in self.contours:
            self.contours[trace.name].append(trace)
        else:
            self.contours[trace.name] = Contour(trace.name, [trace])

        self.added_traces.append(trace)

        self._dualWriteAppend(trace)  # test-only; a no-op in every shipped launch

    def removeTrace(self, trace : Trace, log_event=True):
        """Remove a trace from the trace dictionary.
        
            Params:
                trace (Trace): the trace to remove from the traces dictionary
                log_event (bool): true if the event should be logged
        """
        if trace.name in self.contours:
            self.contours[trace.name].remove(trace)
            self.removed_traces.append(trace)
            self._dualWriteRemove(trace)  # test-only; see the harness block above
        if log_event:
            self.series.addLog(trace.name, self.n, "Delete trace(s)")
    
    def addFlag(self, flag : Flag, log_event=True):
        """Add a flag to the section.
        
            Params:
                flag (Flag): the flag to add to the section
                log_event (bool): true if the event should be logged
        """
        self.flags.append(flag)
        self.flags_modified = True
        if log_event:
            self.series.addLog(None, self.n, "Create flag(s)")
    
    def removeFlag(self, flag : Flag, log_event=True):
        """Remove a flag from the section.
        
            Params:
                flag (Flag): the flag to remove from the section
                log_event (bool): true if the event should be logged
        """
        if flag in self.flags:
            self.flags.remove(flag)
            self.flags_modified = True
            if log_event:
                self.series.addLog(None, self.n, "Delete flag(s)")

    def editTraceAttributes(self, traces : list[Trace], name : str, color : tuple, tags : set, mode : tuple, add_tags=False, log_event=True):
        """Change the name and/or color of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to modify
                name (str): the new name
                color (tuple): the new color
                tags (set): the new set of tags. None leaves each trace's own
                    tags untouched (as for name/color/mode); an empty set
                    REPLACES them with no tags, which is how
                    Series.removeAllTraceTags clears them. The set is copied
                    per trace, so the caller's set is never adopted and no two
                    traces share one.
                mode (tuple): the new fill mode for the traces
                add_tags (bool): True if tags should be added (rather than replaced)
                log_event (bool): true if the event should be logged
        """
        for trace in traces.copy():
            # check if trace was highlighted
            if trace in self.selected_traces:
                self.selected_traces.remove(trace)
                selected = True
            else:
                selected = False
            
            # remove the trace and modify
            self.removeTrace(trace, log_event=False)
            new_trace = trace.copy()
            if name is not None:
                new_trace.name = name
            if color is not None:
                new_trace.color = color
            if tags is not None:
                if add_tags:
                    for tag in tags:
                        new_trace.tags.add(tag)
                else:
                    # copy per trace: a bare assignment would hand the same set
                    # object to every trace in the loop (and to the caller, whose
                    # set it is), so a later in-place tags.add on one trace would
                    # appear on all of them. Trace.copy() copies tags for the
                    # same reason.
                    new_trace.tags = set(tags)
            fill_mode = list(new_trace.fill_mode)
            if mode is not None:
                style, condition = mode
                if style is not None:
                    fill_mode[0] = style
                if condition is not None:
                    fill_mode[1] = condition
                new_trace.fill_mode = tuple(fill_mode)
            
            # log the event
            if log_event:
                if trace.name != new_trace.name:
                    self.series.addLog(trace.name, self.n, f"Rename to {new_trace.name}")
                    self.series.addLog(new_trace.name, self.n, f"Create trace(s) from {trace.name}")
                else:
                    self.series.addLog(new_trace.name, self.n, f"Modify trace(s)")
            
            # add trace back to scene and highlight if needed
            self.addTrace(new_trace, log_event=False)
            if selected:
                self.addSelectedTrace(new_trace)
    
    def editTraceRadius(self, traces : list[Trace], new_rad : float, log_event=True):
        """Change the radius of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to change
                new_rad (float): the new radius for the trace(s)
                log_event (bool): true if the event should be logged
        """
        for trace in traces:
            a = self.series.getAttr(trace.name, "alignment")
            if not a: a = self.series.alignment
            tform = self.tforms[a]
            self.removeTrace(trace, log_event=False)
            trace.resize(new_rad, tform)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify radius")
    
    def editTraceShape(self, traces : list[Trace], new_shape : list, log_event=True):
        """Change the shape of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to change
                new_shape (list): the new shape for the trace(s)
                log_event (bool): true if the event should be logged
        """
        for trace in traces:
            self.removeTrace(trace, log_event=False)
            trace.reshape(new_shape, self.tform)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify shape")
    
    def findClosest(
            self,
            field_x : float,
            field_y : float,
            radius=0.5,
            traces_in_view : list[Trace] = None,
            include_hidden=False):
        """Find closest trace/ztrace to field coordinates in a given radius.
        
        (Only meant for GUI use.)
        
            Params:
                field_x (float): x coordinate of search center
                field_y (float): y coordinate of search center
                radius (float): 1/2 of the side length of search square
                traces_in_view (list): the traces in the window viewed by the user
                include_hidden (bool): True if hidden traces can be returned
            Returns:
                (tuple): the object closest to the point and the type
                None if no trace points are found within the radius
        """
        min_distance = -1
        closest = None
        closest_type = None
        min_interior_distance = -1
        closest_trace_interior = None
        tform = self.tform

        # only check the traces within the view if provided
        if traces_in_view:
            traces = traces_in_view
        else:
            traces = self.tracesAsList()

        # Bbox rejection (hot path: this method runs on every buttonless
        # mouse move for every trace in view). Build the search square in
        # field space -- padded by the radius plus a couple of mag units,
        # since getDistanceFromTrace quantizes coordinates to the mag grid --
        # and inverse-map its corners into trace space. The axis-aligned bbox
        # of those corners is a conservative search window: any trace whose
        # own bbox misses it cannot pass the radius check or contain the
        # point, so it is skipped before any numpy mapping or cv2 test.
        margin = radius + 2 * self.mag
        try:
            search_corners = tform.map(
                [
                    (field_x - margin, field_y - margin),
                    (field_x + margin, field_y - margin),
                    (field_x + margin, field_y + margin),
                    (field_x - margin, field_y + margin),
                ],
                inverted=True,
            )
            sxs = [p[0] for p in search_corners]
            sys_ = [p[1] for p in search_corners]
            s_xmin, s_xmax = min(sxs), max(sxs)
            s_ymin, s_ymax = min(sys_), max(sys_)
        except Exception:
            # a degenerate/non-invertible section transform cannot be
            # inverse-mapped. Fall back to an unbounded search window so no
            # trace is bbox-rejected: every trace is still forward-mapped and
            # distance-tested in the loop below, exactly as the old forward-map
            # loop did. Hover (a buttonless mouse move) must never crash here.
            s_xmin = s_ymin = float("-inf")
            s_xmax = s_ymax = float("inf")

        # iterate through all traces to get closest
        for trace in traces:
            # skip hidden traces
            if not include_hidden and trace.hidden:
                continue
            if not trace.points:
                continue

            # bbox-reject in trace space (cheap C-level min/max)
            xs, ys = zip(*trace.points)
            if (
                max(xs) < s_xmin or min(xs) > s_xmax or
                max(ys) < s_ymin or min(ys) > s_ymax
            ):
                continue

            # map every surviving trace's points in one vectorized call
            points = tform.mapPointsArray(trace.points)

            # find the distance of the point from each trace
            dist = getDistanceFromTrace(
                field_x,
                field_y,
                points,
                factor=1/self.mag,
                absolute=False
            )
            if closest is None or abs(dist) < min_distance:
                min_distance = abs(dist)
                closest = trace
                closest_type = "trace"
            
            # check if the point is inside any filled trace
            if (
                trace.fill_mode[0] != "none" and
                dist > 0 and 
                (closest_trace_interior is None or dist < min_interior_distance)
            ):
                min_interior_distance = dist
                closest_trace_interior = trace
        
        # check for ztrace points close by
        if self.series.getOption("show_ztraces"):
            for ztrace in self.series.ztraces.values():
                for i, pt in enumerate(ztrace.points):
                    if pt[2] == self.n:
                        x, y = tform.map(*pt[:2])
                        dist = distance(field_x, field_y, x, y)
                        if closest is None or dist < min_distance:
                            min_distance = dist
                            closest = (ztrace, i)
                            closest_type = "ztrace_pt"
        
        # check for flags close by
        show_flags = self.series.getOption("show_flags")
        if show_flags != "none":
            for flag in self.flags:
                if show_flags == "unresolved" and flag.resolved:
                    continue
                x, y = tform.map(flag.x, flag.y)
                dist = distance(field_x, field_y, x, y)
                if closest is None or dist < min_distance:
                    min_distance = dist
                    closest = flag
                    closest_type = "flag"
        
        # check for radius and if pointer is in interior
        if min_distance > radius:
            if closest_trace_interior:
                closest = closest_trace_interior
                closest_type = "trace"
            else:
                closest = None
                closest_type = None

        return closest, closest_type
    
    def deselectAllTraces(self):
        """Deselect all traces.
        
        (Only meant for GUI use.)
        """
        self.selected_traces : list[Trace] = []
        self.selected_ztraces = []
        self.selected_flags = []
    
    def selectAllTraces(self):
        """Select all traces.

        (Only meant for GUI use.)
        """
        self.deselectAllTraces()
        for trace in self.tracesAsList():
            self.addSelectedTrace(trace)

    def invertTraceSelection(self, include_hidden=False):
        """Invert the trace selection: deselect every selected trace and
        select every unselected trace.

        Only traces visible in the field can become selected: hidden and
        group-hidden traces are skipped unless include_hidden is True (the
        show-all-traces mode). A locked object's traces are selected like any
        other, which is what the object list's invert already does: lock guards
        edits, not selection. Selected ztrace points and flags are left
        untouched.

        (Only meant for GUI use.)

            Params:
                include_hidden (bool): True if hidden traces may be selected
        """
        selected = set(self.selected_traces)
        group_hidden = set(self.traces_group_hide)

        to_select = []
        for trace in self.tracesAsList():
            if trace in selected:
                continue
            if not include_hidden and (trace.hidden or trace in group_hidden):
                continue
            to_select.append(trace)

        self.selected_traces : list[Trace] = []
        for trace in to_select:
            self.addSelectedTrace(trace)

    def hideOtherTraces(self, keep : list = None, log_event=True):
        """Hide every trace on THIS section except the given ones (the selected
        traces by default).

        Locked traces in the complement are hidden too: locking guards edits and
        quantification, not visibility. Traces already hidden are left untouched.
        An empty keep set is a no-op, so this never blanks the section.

        (Only meant for GUI use.)

            Params:
                keep (list): the traces to keep visible (defaults to selection)
                log_event (bool): true if the event should be logged
            Returns:
                (bool): True if the section was modified
        """
        if keep is None:
            keep = self.selected_traces
        keep_set = set(keep)
        if not keep_set:  # never hide every trace on the section
            return False

        modified = False
        for trace in self.tracesAsList():
            if trace in keep_set or trace.hidden:
                continue
            modified = True
            trace.setHidden(True)
            self._dualWriteAttribute(trace, "hidden", True)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")

        # drop any traces that are now hidden from the selection
        self.selected_traces = [t for t in self.selected_traces if not t.hidden]

        return modified

    def hideTraces(self, traces : list = None, hide=True, log_event=True):
        """Hide traces.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to hide
                hide (bool): True if traces should be hidden
                log_event (bool): true if the event should be logged
        """
        modified = False

        if not traces:
            traces = self.selected_traces.copy()

        for trace in traces:
            modified = True
            trace.setHidden(hide)
            self._dualWriteAttribute(trace, "hidden", hide)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        self.selected_traces : list[Trace] = []

        return modified

    def setGroupVisibility(self, group_viz: Union[Dict[str, bool], None]=None) -> None:
        """Modify traces_group_hide based on group visibility.

            Params:
                group_viz (dict): group name -> True if the group is visible.
                                  Omitted, None, or empty means there is nothing
                                  to apply and traces_group_hide is left alone.
        """
        ## Nothing to apply: leave traces_group_hide as it is
        if not group_viz:

            return

        ## Get list of groups to hide
        hide_groups = [group for group, viz in group_viz.items() if not viz]

        if not hide_groups:

            return

        obj_groups = self.series.object_groups

        to_hide = set()
        
        for group in hide_groups:
            
            objs = obj_groups.getGroupObjects(group)
            to_hide = to_hide.union(objs)

        if not to_hide:

            return

        # only visit contours that are actually hidden (avoids scanning every
        # trace on the section and rebuilding a list per trace)
        for name in (to_hide & self.contours.keys()):

            self.traces_group_hide.extend(self.contours[name])

    def closeTraces(self, traces : list = None, closed=True, log_event=True):
        """Close or open traces.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to modify
                closed (bool): True if traces should be closed
                log_event (bool): true if the event should be logged
        """
        modified = False

        if not traces:
            traces = self.selected_traces

        for trace in traces:
            modified = True
            trace.closed = closed
            self._dualWriteAttribute(trace, "closed", closed)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        return modified
    
    def unhideAllTraces(self, log_event=True):
        """Unhide all traces on the section.

        (Only meant for GUI use.)
        
            Params:
                log_event (bool): true if the event should be logged
        """
        modified = False
        for trace in self.tracesAsList():
            hidden = trace.hidden
            if hidden:
                modified = True
                trace.setHidden(False)
                self._dualWriteAttribute(trace, "hidden", False)  # test-only
                self.modified_contours.add(trace.name)
                if log_event:
                    self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        return modified
    
    def makeNegative(self, traces : list = None, negative=True, log_event=True):
        """Make a set of traces negative.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to make negative
                negative (bool): the negative status of the traces to modify
                log_event (bool): true if the event should be logged
        """
        if traces is None:
            traces = self.selected_traces.copy()
        modified = False

        for trace in traces:
            self.removeTrace(trace, log_event=False)
            trace.negative = negative
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
            modified = True
        
        return modified
        
    def deleteTraces(self, traces : Union[List, None] = None, flags : Union[List, None] = None, log_event=True):
        """Delete selected traces and flags.
        
            Params:
                traces (list): a list of traces to delete (default is selected traces)
                flags (list): a list of flags to delete (defaults to selected
                    flags only when traces is also defaulted)
                log_event (bool): True if event should be logged
        """
        modified = False

        traces_defaulted = traces is None
        if traces_defaulted:
            traces = self.selected_traces.copy()

        for trace in traces:
            modified = True
            self.removeTrace(trace, log_event)
            if trace in self.selected_traces:
                self.selected_traces.remove(trace)

        if flags is None:
            # fall back to the selected flags only when the caller also
            # defaulted traces (i.e. "delete the selection"); callers that
            # pass an explicit trace list (cut/merge/scalpel/scissors) must
            # not delete selected flags as a side effect
            flags = self.selected_flags.copy() if traces_defaulted else []
        
        for flag in flags:
            modified = True
            self.removeFlag(flag, log_event)
            if flag in self.selected_flags:
                self.selected_flags.remove(flag)

        return modified
    
    def translateTraces(self, dx : float, dy : float, log_event=True):
        """Translate the selected traces.
        
            Params:
                dx (float): x-translate
                dy (float): y-translate
                log_event (bool): True if event should be logged
        """
        tform = self.tform

        for trace in self.selected_traces:
            self.removeTrace(trace, log_event=False)
            for i, p in enumerate(trace.points):
                # apply forward transform
                x, y = tform.map(*p)
                # apply translate
                x += dx
                y += dy
                # apply reverse transform
                x, y = tform.map(x, y, inverted=True)
                # replace point
                trace.points[i] = (x, y)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        for ztrace, i in self.selected_ztraces:
            x, y, snum = ztrace.points[i]
            # apply forward tform
            x, y = tform.map(x, y)
            # apply translate
            x += dx
            y += dy
            # apply reverse transform
            x, y = tform.map(x, y, inverted=True)
            # replace point
            ztrace.points[i] = (x, y, snum)
            # keep track of modified ztrace
            self.series.modified_ztraces.add(ztrace.name)
            if log_event:
                self.series.addLog(ztrace.name, self.n, "Modify ztrace")
        
        for flag in self.selected_flags:
            # apply forward tform
            x, y = tform.map(flag.x, flag.y)
            # apply translate
            x += dx
            y += dy
            # apply reverse tform
            x, y = tform.map(x, y, inverted=True)
            # replace point
            flag.x, flag.y = x, y
            # keep track of modified flag
            if log_event:
                self.series.addLog(None, self.n, "Modify flag")
    
    def addImportFlag(self, prefix : str, cname : str, trace : Trace, comment : str):
        """Flag a trace an import acted on, with a comment saying why.

            Params:
                prefix (str): the flag name prefix, e.g. "import-removed"
                cname (str): the name of the contour
                trace (Trace): the trace to flag (used for position and colour)
                comment (str): the explanation shown to the reviewer
        """
        x, y = trace.getCentroid()
        flag = Flag(f"{prefix}_{cname}", x, y, self.n, trace.color)
        flag.addComment(self.series.user, comment)
        self.flags.append(flag)

    def flagImportConflicts(self, cname : str, traces : list, reason : str):
        """Flag traces an import kept because it could not safely choose between them.

            Params:
                cname (str): the name of the contour
                traces (list): the traces to flag
                reason (str): the explanation shown to the reviewer
        """
        for trace in traces:
            self.addImportFlag("import-conflict", cname, trace, reason)

    def recordImportRemoval(self, cname : str, traces : list, reason : str):
        """Record traces that an import removed, as a flag and as a log entry.

        An import is only ever allowed to destroy annotation work that a human's
        own recorded action licenses, and never without leaving behind both a
        flag a reviewer can find and a log entry the next merge can see. This is
        deliberately NOT gated on the "flag conflicts" option: that option is
        about conflicts, where both versions survive and somebody has to choose.
        A record of destroyed work is not optional.

            Params:
                cname (str): the name of the contour
                traces (list): the traces that were removed
                reason (str): the explanation shown to the reviewer
        """
        if not traces:
            return

        for trace in traces:
            self.addImportFlag(
                "import-removed", cname, trace,
                f"Trace removed by an import: {reason}.",
            )

        self.series.addLog(cname, self.n, "Remove trace(s) during import")

    def importTraces(
            self,
            other,
            regex_filters: list=[],
            group_filters: list=[],
            threshold : float=0.95, 
            flag_conflicts : bool=True, 
            histories : LogSetPair=None, 
            keep_above : str="self",
            keep_below : str="",
            dt_str : str=None
    ):
        """Import the traces from another section.
        
            Params:
                other (Section): the section with traces to import
                regex_filters (list): regex filters for objects
                group_filters (list): group filters for objects
                threshold (float): the overlap threshold
                flag_conflicts (bool): True if conflicts should be flagged
                histories (LogSetPair): the self history and the other history
                keep_above (str): the series that is favored for functional duplicates (above the overlap threshold; "self", "other", or "")
                keep_below (str): the series that is favored in the case of a conflict (overlap not reaching the threshold; "self", "other", or "")
                dt_str (str): the datetime string for tagging purposes
        """

        all_contour_names = list(
            set(self.contours.keys()) | set(other.contours.keys())
        )

        if group_filters:

            other_groups = other.series.object_groups.getGroupDict()
        
        for cname in all_contour_names:

            if not passesFilters(cname, regex_filters):

                continue

            if group_filters:

                passes_filter = False

                for gf in group_filters:

                    if cname in other_groups[gf]:
                        passes_filter = True

                if not passes_filter:

                    continue

            ## Flag as modified
            self.modified_contours.add(cname)

            ## Create empty contour if does not exist
            if cname not in self.contours:
                self.contours[cname] = Contour(cname, [])
                
            if cname not in other.contours:
                other.contours[cname] = Contour(cname, [])
            
            ## Adjust contours in other series to match current series mag
            mags_match = abs(other.mag - self.mag) <= 1e-8

            if not mags_match:
                
                for trace in other.contours[cname]:
                    trace.magScale(other.mag, self.mag)

            # Check the histories to find which contour has been modified since
            # the two series diverged.
            #
            # The history gives one Boolean per side: "does this side's log
            # mention this contour after the divergence point?" A True is
            # positive evidence that somebody edited the contour. A False is
            # only SILENCE, and silence is not proof that a side is unchanged --
            # logs get trimmed, get rewritten when an object is deleted, and are
            # suppressed outright while an import runs, so anything a previous
            # merge brought in reads as untouched. Acting on a False therefore
            # used to destroy real annotation work: the (False, False) branch
            # discarded the other contour whole and the (False, True) branch
            # replaced ours with theirs, in both cases without comparing a
            # single point and without leaving a flag behind.
            #
            # So the shortcut is now checked against the data before it is
            # taken. It may discard a trace only if that trace overlaps
            # something on the surviving side (making it a version of it) or if
            # a log entry records it as deliberately removed -- and a discarded
            # trace always leaves a flag and a log entry. Anything else is
            # independent work, which means the history cannot decide this
            # contour: keep both sides and flag the disagreement.
            history_orphans = []

            if histories and not histories.complete_match and histories.last_shared_index >= 0:
                # determine which series have been modified since diverge
                modified_since_diverge = histories.getModifiedSinceDiverge(cname, self.n)

                # (True, True) is the case a merge exists for; fall through to
                # the geometric merge below. Everything else has a shortcut.
                if not all(modified_since_diverge):
                    # the shortcut keeps one contour and discards the other: the
                    # side the log says changed, or -- when the log mentions
                    # neither -- the current series', which the two contours are
                    # being assumed to already agree on
                    take_other = modified_since_diverge[1]
                    keeper = other.contours[cname] if take_other else self.contours[cname]
                    donor = self.contours[cname] if take_other else other.contours[cname]

                    # the traces the shortcut would destroy outright
                    orphans = tracesWithoutCounterpart(donor, keeper)

                    # only ask the log about a removal if something is at stake:
                    # the scan is linear in the log length
                    deliberate = bool(orphans) and histories.getRemovedSinceDiverge(
                        cname, self.n
                    )[1 if take_other else 0]

                    if orphans and not deliberate:
                        # The log claims one side is untouched, yet that side
                        # holds traces the other has nothing over at all, and
                        # nothing in the log says they were removed on purpose.
                        # Decline the shortcut: the geometric merge below keeps
                        # both sides, and these traces get flagged.
                        history_orphans = orphans
                    else:
                        if take_other:
                            self.contours[cname] = other.contours[cname]
                        if orphans:
                            # a removal recorded by a human is being propagated;
                            # it is allowed to destroy work, but never silently
                            self.recordImportRemoval(
                                cname,
                                orphans,
                                "the other series' history records it as deliberately removed"
                                if take_other else
                                "this series' history records it as deliberately removed",
                            )
                        if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty
                        continue

            # import the contour
            ## self.mag, not other.mag: the loop above has already brought the
            ## other series' traces onto this section's magnification with
            ## Trace.magScale, so the comparison happens entirely in these units.
            conflict_traces_s, conflict_traces_o = self.contours[cname].importTraces(
                other.contours[cname], threshold, keep_above, self.mag
            )

            # A history shortcut was declined above because it would have
            # destroyed traces with no counterpart on the surviving side. The
            # merge has kept them; flag them here, before the short-circuit
            # below, because one of the conflict pools is usually empty in this
            # situation and the flagging step at the bottom would skip them.
            if history_orphans and flag_conflicts:
                self.flagImportConflicts(
                    cname,
                    history_orphans,
                    "kept because the two series' histories disagree with their "
                    "traces: one history reports this contour unmodified, but "
                    "this trace has no counterpart in the other series",
                )

            # if one or both series have no conflicts, no need to flag them or check for favor below the threshold
            if not conflict_traces_s or not conflict_traces_o:
                if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty
                continue

            # iterate through conflict pool and favor the requested traces
            if keep_below in ("self", "other"):
                # set traces1 variable to be favored traces and traces2 to be unfavored traces
                if keep_below == "self":
                    traces1, traces2 = conflict_traces_s, conflict_traces_o
                elif keep_below == "other":
                    traces1, traces2 = conflict_traces_o, conflict_traces_s
                # iterate through traces and delete overlaps in unfavored series
                removed_by_policy = []
                for trace1 in traces1:
                    for trace2 in traces2.copy():
                        ## open_curve=False for the same reason as
                        ## tracesWithoutCounterpart above, which is written out
                        ## there: threshold=0 asks "do these overlap at all", the
                        ## curve metric was measured for "are these the same
                        ## trace", and this site deletes a trace on the answer.
                        if trace1.overlaps(trace2, threshold=0, open_curve=False):
                            traces2.remove(trace2)
                            self.contours[cname].remove(trace2)
                            removed_by_policy.append(trace2)
                # clear favored traces, as they will never be conflicts
                traces1.clear()
                # any traces left in unfavored traces will be flagged
                #
                # The two lines above are why this needs recording: the
                # unfavoured traces have been removed from the contour and the
                # favoured pool has been emptied, so the flagging step below has
                # nothing left to flag and the traces would simply be gone.
                if removed_by_policy:
                    favoured = (
                        "the current series"
                        if keep_below == "self" else "the importing series"
                    )
                    self.recordImportRemoval(
                        cname,
                        removed_by_policy,
                        "the import was asked to keep traces from "
                        f"{favoured} only where the overlap is below the threshold",
                    )

            # flag the remaining conflicts
            if flag_conflicts:                                     
                for trace in conflict_traces_s:
                    if dt_str:
                        trace.tags.add(f"{dt_str}-ic1")
                    x, y = trace.getCentroid()
                    self.flags.append(Flag(f"import-conflict_{trace.name}", x, y, self.n, trace.color))
                for trace in conflict_traces_o:
                    if dt_str:
                        trace.tags.add(f"{dt_str}-ic2")
                    x, y = trace.getCentroid()
                    self.flags.append(Flag(f"import-conflict_{trace.name}", x, y, self.n, trace.color))
            
            if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty

        # An import rebinds whole contour trace lists rather than going through
        # addTrace/removeTrace, so there is no sequence of row operations to
        # mirror. Rebuild the test-only store from the result instead of
        # pretending it was tracked. `other` is rebuilt too, because the mag
        # loop above rewrote ITS traces' coordinates in place. Guarded on
        # `self._columns` rather than left to `_dualWriteResync`'s own guard so
        # that with the gate off -- every shipped launch -- `other` is not
        # touched at all and need not be a real `Section`.
        if self._columns is not None:
            self._dualWriteResync()
            other._dualWriteResync()

        self.save()

    def addSelectedTrace(self, trace : Trace):
        """Add a trace to the selected trace list.

        Locking an object does not affect selection. Lock prevents mutations
        that change quantitative data (traces added, deleted or modified), and
        every field operation that does one of those carries its own check:
        `FieldWidgetTrace.refuseLockedTraces` for the six that read the
        selection directly, `trace_function` for the trace context menu and
        `object_function(update_objects=True)` for the object one.

        This used to refuse a locked object's trace, which made it the only
        thing standing between a locked object and those operations. It was
        also visible to the user as an inconsistency: the field's invert
        selection silently skipped locked objects while the object list
        selected locked rows freely.

            Params:
                trace (Trace): the trace to append to the list.
        """
        self.selected_traces.append(trace)

    def exportAsSVG(self, svg_fp):
        """Export untransformed section as svg."""

        return export_svg(self, svg_fp)

    def exportAsPNG(self, png_fp, scale: float=1.0):
        """Export untransformed section as png."""

        return export_png(self, png_fp, scale)
        

class TransformsDict(dict):
    
    def __init__(self):
        super().__init__()
        self["no-alignment"] = Transform.identity()
    
    def __setitem__(self, key, value) -> None:
        if key == "no-alignment" and not value.equals(Transform.identity()):
            raise Exception("Cannot change transform for 'no-alignment'.")
        else:
            return super().__setitem__(key, value)
    
    def __delitem__(self, key) -> None:
        if key == "no-alignment":
            raise Exception("Cannot delete transform for 'no-alignment'.")
        else:
            return super().__delitem__(key)

import os
import json
import shutil
import itertools
from copy import deepcopy

from PyReconstruct.modules.datatypes import (
    Series,
    Section,
    Contour,
    Ztrace,
    Trace
)
from PyReconstruct.modules.datatypes.trace import copyObjDefaults

from PyReconstruct.modules.constants import keyed_trace_row_to_positional

# Undo and redo order comes from comparing these stamps (see favor3D), so they
# come from one counter shared by field and series states. A wall clock in
# tenths of a second gave two undos inside the same tenth equal stamps (a held
# Cmd+Z repeats faster than that), and a clock set back made a newer step look
# older; either way redo could replay a series step and a section step in the
# wrong order.
_stamps = itertools.count(1)

def nextStamp() -> int:
    """Return a stamp greater than every stamp handed out before it."""
    return next(_stamps)

class FieldState():

    def __init__(
            self, 
            contours : dict, 
            ztraces : dict, 
            tforms : dict, 
            flags : list,
            contours_fp : str = None,
            updated_contours=None,
            updated_ztraces=None,
            src_fp : str = None
        ):
        """Create a field state with traces and the transform.

            Params:
                contours (dict): all the contours on a section
                tforms (dict): the tforms for the section state
                flags (list): the flags for the section state
                contours_fp (str): the filepath to store the contours
                updated_contours: the names of the modified contours
                updated_ztraces: the names of the modified ztraces
                src_fp (str): if given, the section's on-disk file, whose
                    bytes are copied to contours_fp as the baseline instead of
                    re-serializing the contours. Only valid when that file
                    still equals the in-memory contours (see initialize).
        """
        self.contours = {}
        self.contours_fp = contours_fp
        # object attributes and groups to restore on redo (objectSnapshot)
        self.obj_snapshot = {}
        # name -> object id, for each contour held here that has traces
        # (captureObjectIds); undo and redo put these back
        self.oids = {}
        if updated_contours is None:
            if contours is None:
                updated_contours = []
            else:
                updated_contours = contours.keys()

        # store contours in memory if no fp provided
        if not self.contours_fp:  
            for contour_name in updated_contours:
                if contour_name in contours:
                    self.contours[contour_name] = contours[contour_name].copy()
                else:  # empty Contour
                    self.contours[contour_name] = Contour(contour_name)
        # store contours in json
        elif contours is None:  # assume stored in JSON already
            self.contours = None
        else:
            baseline_preexisted = os.path.isfile(self.contours_fp)
            try:
                if src_fp is not None:  # copy the section's on-disk file as baseline
                    # The section is unmodified since it was loaded, so its on-disk
                    # file already equals this baseline. Copy the bytes rather than
                    # re-serializing every contour (the dominant cost of the first
                    # edit to an object's sections on large series). getContours reads
                    # this section-file layout back.
                    shutil.copyfile(src_fp, self.contours_fp)
                else:  # store contours if provided with both fp and contours
                    json_contours = {}
                    for contour_name in updated_contours:
                        json_contours[contour_name] = [trace.getList() for trace in contours[contour_name]]
                    with open(self.contours_fp, "w", encoding="utf-8") as f:
                        json.dump(json_contours, f)
                self.contours = None
            except OSError:
                # the baseline could not be written (e.g. a read-only install
                # dir): clean up and keep the state in memory instead. Only
                # remove a file this call created -- a pre-existing file is
                # someone else's (the bundled welcome.0.s0 was being deleted
                # outright when the install's files were read-only but its
                # directory was not), and we never wrote a byte of it.
                try:
                    if not baseline_preexisted and os.path.isfile(self.contours_fp):
                        os.remove(self.contours_fp)
                except OSError:
                    pass
                self.contours_fp = None
                self.contours = {}
                for contour_name in updated_contours:
                    if contour_name in contours:
                        self.contours[contour_name] = contours[contour_name].copy()
                    else:  # empty Contour
                        self.contours[contour_name] = Contour(contour_name)
        
        self.ztraces = {}
        # first state made for a section (or copy)
        if updated_ztraces is None:
            for ztrace_name in ztraces:
                self.ztraces[ztrace_name] = ztraces[ztrace_name].copy()
        # added another state
        else:
            for ztrace_name in updated_ztraces:
                self.ztraces[ztrace_name] = ztraces[ztrace_name].copy()
        
        # save tforms
        self.tforms = {}
        for alignment_name in tforms:
            self.tforms[alignment_name] = tforms[alignment_name].copy()
        
        # save flags
        self.flags = []
        for flag in flags:
            self.flags.append(flag.copy())

        # Every state carries a time from birth, so reading it is always safe.
        # `favor3D` compares the newest 2D and 3D states to decide which undo
        # Ctrl+Z should take, and it read this attribute off states that had
        # never been through `SectionStates.addState`, which was the only place
        # that set it. Two routes produce such a state: an undo pushes
        # `current_state` straight onto `redo_states`, and the state it pops
        # back is a `copy()`, which rebuilds through this constructor. Either
        # leaves a state on a stack with no `time` at all, so a later Ctrl+Z
        # raised AttributeError instead of undoing anything (reported against
        # v1.21.2). `updateTime` still restamps a state as it goes onto a
        # stack; this is the floor under that, not a replacement for it.
        self.time = nextStamp()

        # group -> visibility, for each group the undo of this state emptied
        # (see dropEmptiedGroups); the redo of this state reads it first
        self.group_viz = {}
        # the same, for each group this state's action or its redo emptied
        # (deleting an object's last trace); the undo of this state reads it
        self.undo_group_viz = {}

    def copy(self):
        c = FieldState(self.contours, self.ztraces, self.tforms, self.flags, self.contours_fp)
        c.obj_snapshot = deepcopy(self.obj_snapshot)
        c.oids = dict(self.oids)
        c.group_viz = dict(self.group_viz)
        c.undo_group_viz = dict(self.undo_group_viz)
        return c
    
    def getContours(self):
        contours = {}
        if self.contours_fp:
            with open(self.contours_fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("contours"), dict):
                # baseline copied from the on-disk section file: parse its
                # contours exactly as Section.__init__ does (screening out
                # defective traces) so the restored state matches a fresh load
                for cname, trace_list in data["contours"].items():
                    traces = []
                    for trace_data in trace_list:
                        # A KEYED ROW MUST BE DECODED BEFORE fromList SEES IT,
                        # and this is the one place in the read path where
                        # skipping it does not raise. `Trace.fromList` handed a
                        # dict does not fail: `len(dict)` is the key count and
                        # iterating a dict yields its keys, so an 8-key row
                        # unpacks the eight KEY STRINGS into the eight fields
                        # and a 9-key row additionally takes the first key as
                        # the name. The undo baseline silently became a `Trace`
                        # named 'x' whose points were pairs of key names, and
                        # the first undo restored that over the user's real
                        # traces.
                        #
                        # This path reads the section file verbatim
                        # (`shutil.copyfile` above), so it never sees
                        # `Section.updateJSON` and has to know the shape itself.
                        # The row's `id` is deliberately ignored: the baseline
                        # restores the object model, and a trace's id lives in
                        # the columnar store rather than on the `Trace`.
                        if type(trace_data) is dict:
                            trace_data = keyed_trace_row_to_positional(trace_data)
                        trace = Trace.fromList(trace_data, cname)
                        l = len(trace.points)
                        if l == 2:
                            trace.closed = False
                        if l > 1:
                            traces.append(trace)
                    contours[cname] = Contour(cname, traces)
            else:
                # baseline serialized as a contours-only dict (dirty-section
                # fallback and pre-existing .s0 files)
                for cname, contour in data.items():
                    contours[cname] = Contour(cname, [Trace.fromList(trace) for trace in contour])
            return contours
        else:
            for cname in self.contours:
                contours[cname] = self.contours[cname].copy()
            return contours
    
    def getZtraces(self):
        ztraces = {}
        for zname in self.ztraces:
            ztraces[zname] = self.ztraces[zname].copy()
        return ztraces
    
    def getModifiedContours(self):
        if self.contours_fp:
            with open(self.contours_fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("contours"), dict):
                return set(data["contours"].keys())
            return set(data.keys())
        else:
            return set(self.contours.keys())
    
    def getModifiedZtraces(self):
        return set(self.ztraces.keys())
    
    def getTforms(self):
        return self.tforms.copy()

    def getFlags(self):
        return self.flags.copy()
    
    def updateTime(self):
        self.time = nextStamp()  # keep track of when it was added to a state list

def _objectIds(series : Series):
    """The series' object id registry (datatypes/object_ids.py), or None
    for a stand-in series that has none."""
    return getattr(getattr(series, "data", None), "object_ids", None)

def captureObjectIds(series : Series, section : Section, names, assign=False) -> dict:
    """The object id of each named contour with traces on the section.

        Params:
            series (Series): the series
            section (Section): the section
            names: the contour names to capture
            assign (bool): True to give an id to a contour that has none yet
                (an action just drew it, and the series data has not caught
                up); False to only read the ids
        Returns:
            (dict): name -> object id
    """
    ids = _objectIds(series)
    if ids is None:
        return {}
    oids = {}
    for name in names:
        if not len(section.contours.get(name, ())):
            continue
        oid = ids.ensure(section.n, name) if assign else ids.peek(section.n, name)
        if oid is not None:
            oids[name] = oid
    return oids

def restoreObjectIds(series : Series, section : Section, names, oids : dict):
    """Put back the object id each restored contour had in the state it
    came from. A contour the state holds no id for takes one by the usual
    rule (ObjectIds.ensure); a contour left empty has none.

        Params:
            series (Series): the series
            section (Section): the section just restored
            names: the names of the restored contours
            oids (dict): name -> the id the state recorded
    """
    ids = _objectIds(series)
    if ids is None:
        return
    for name in names:
        if not len(section.contours.get(name, ())):
            ids.drop(section.n, name)
            continue
        oid = oids.get(name)
        if oid is not None and ids.name_of.get(oid) == name:
            ids.place(section.n, name, oid)
        else:
            ids.ensure(section.n, name)

def objectSnapshot(series : Series, names, before : dict = None) -> dict:
    """What an undo step must bring back with an object it recreates.

    Undoing an object's last trace deletes the object, and SeriesData then
    clears its attributes and group memberships (removeObjAttrs). The section
    undo states hold only traces, transforms and flags, so a redo used to bring
    the trace back bare: a palette button's groups and custom columns (fork
    #419), set when the trace was drawn, were gone. Each state now keeps a copy
    of those for the objects it touched, and of their hosts and travelers.

    The copy is taken when the action's state is added, before SeriesData
    sees the action, so a state whose action deletes an object still holds
    what the object carried. Undoing that action puts it back. An object list
    action saves each section before its state is added, so it reads
    ``before`` instead (SeriesStates.addSectionUndo).

        Params:
            series (Series): the series
            names (iterable): the object names the state touched
            before (dict): series attributes to read instead of the series
                (SeriesState.getSeriesAttributes)
        Returns:
            (dict): name -> {"attrs": dict, "groups": list, "hosts": list,
                "travelers": list}, only for names that have any of them
    """
    if before is None:
        obj_attrs, object_groups, host_tree = (
            series.obj_attrs, series.object_groups, series.host_tree
        )
    else:
        obj_attrs, object_groups, host_tree = (
            before["obj_attrs"], before["object_groups"], before["host_tree"]
        )
    out = {}
    for name in names:
        attrs = obj_attrs.get(name)
        groups = object_groups.getObjectGroups(name)
        hosts = host_tree.getHosts(name)
        travelers = host_tree.getTravelers(name)
        if attrs or groups or hosts or travelers:
            out[name] = {
                "attrs": deepcopy(attrs) if attrs else {},
                "groups": sorted(groups),
                "hosts": sorted(hosts),
                "travelers": sorted(travelers),
            }
    return out


def restoreObjectSnapshot(series : Series, snapshot : dict, recreated,
                          state_viz : dict = None) -> None:
    """Put a snapshot back on the objects an undo or redo just recreated.

    Only objects that did not exist before the step are touched, so it never
    overwrites attributes an existing object carries. ``state_viz`` is the
    visibility of each group that the opposite step of this same state
    emptied.
    """
    state_viz = state_viz or {}
    emptied_viz = getattr(series, "emptied_group_viz", {})
    recreated = list(recreated)
    # a host or traveler is put back only if it is an object now, or comes
    # back in this same step: the tree must not gain a name nothing traces
    present = set(series.data["objects"]) | set(recreated)
    for name in recreated:
        entry = snapshot.get(name)
        if not entry:
            continue
        for attr_name, value in entry["attrs"].items():
            series.setAttr(name, attr_name, deepcopy(value))
        for group in entry["groups"]:
            # an entry still there is left alone. A group an undo or redo
            # emptied lost its entry, so it gets the visibility it had then
            # (see dropEmptiedGroups): the value the opposite step of this
            # state dropped, else the last value any step dropped, else shown.
            if group not in series.groups_visibility:
                if group in state_viz:
                    value = state_viz[group]
                else:
                    value = emptied_viz.get(group, True)
                series.groups_visibility[group] = value
            series.object_groups.add(group=group, obj=name)
        hosts = [h for h in entry.get("hosts", []) if h in present]
        if hosts:
            series.host_tree.add(name, hosts)
        for traveler in entry.get("travelers", []):
            if traveler in present:
                series.host_tree.add(traveler, [name])

    # a link a delete dropped comes back once both its objects are back
    # (see recordDroppedHostLinks)
    record = getattr(series, "dropped_host_links", None)
    if record:
        back = {
            (t, h) for t, h in record
            if (t in recreated or h in recreated) and t in present and h in present
        }
        for traveler, host in sorted(back):
            series.host_tree.add(traveler, [host])
        record -= back


def hostLinks(series : Series, names) -> set:
    """The (traveler, host) links that touch these objects."""
    links = set()
    for name in names:
        links.update((name, h) for h in series.host_tree.getHosts(name))
        links.update((t, name) for t in series.host_tree.getTravelers(name))
    return links


def recordDroppedHostLinks(series : Series, links_before) -> None:
    """Keep each host link a section step dropped by deleting an object.

    Deleting an object drops its links (removeObjAttrs), and a state's copy
    of an object (objectSnapshot) holds only the links it had when the state
    was made. With H hosting T, H deleted on one section and then T on
    another, T's copy has no link, and the undo of H's delete cannot put the
    link back while T is gone. This record keeps the link until a step
    brings both objects back (restoreObjectSnapshot). It is not saved and
    starts over with the undo history (SeriesStates).

        Params:
            series (Series): the series
            links_before (set): hostLinks of the step's objects before it
    """
    objects = series.data["objects"]
    dropped = {
        (t, h) for t, h in links_before
        if t not in objects or h not in objects
    }
    if dropped:
        record = getattr(series, "dropped_host_links", None)
        if record is None:
            record = series.dropped_host_links = set()
        record |= dropped


def forgetHostLinks(series : Series, names) -> None:
    """Drop the recorded links of objects an action just created: a new
    object with an old name does not take the old object's links."""
    record = getattr(series, "dropped_host_links", None)
    if record:
        names = set(names)
        record -= {(t, h) for t, h in record if t in names or h in names}


def recreatedAlignments(snapshot : dict, recreated) -> dict:
    """The alignment pin of each recreated object that had one.

    SeriesData sets a new object's alignment to the current one when it
    first sees it, so a section undo or redo that brings an object back loses
    the pin it put back. The field puts it back again after that update
    (FieldWidgetBase.undoState).
    """
    out = {}
    for name in recreated:
        alignment = (snapshot.get(name) or {}).get("attrs", {}).get("alignment")
        if alignment is not None:
            out[name] = alignment
    return out


def dropEmptiedGroups(series : Series, groups_before) -> dict:
    """Drop the visibility entry of each group a section undo or redo emptied.

    A section step that deletes an object's last trace deletes the object,
    and its groups go with it (removeObjAttrs), but nothing dropped their
    visibility entries, and `View` > `Groups` lists groups from those
    entries. So an emptied group kept its row, and a later series undo that
    brought the group back found the stale entry and kept it, even when the
    group had been hidden before. Removing a group's last object from the
    group drops the entry the same way.

    The dropped values are kept in two records. The caller puts them on the
    state whose opposite step brings the groups back, which is the value for
    that step. ``series.emptied_group_viz`` also keeps the latest value per
    group, for a step whose own state has none: a group emptied by two steps
    on two sections is recorded only on the state of the step that emptied
    it last. That record is not saved and starts over with the undo history
    (SeriesStates).

        Params:
            series (Series): the series
            groups_before (iterable): the groups before the step
        Returns:
            (dict): group -> its visibility, for each entry dropped
    """
    emptied = set(groups_before) - set(series.object_groups.getGroupList())
    dropped = {}
    for group in emptied:
        if group in series.groups_visibility:
            dropped[group] = series.groups_visibility.pop(group)
    recordEmptiedGroups(series, dropped)
    return dropped


def recordEmptiedGroups(series : Series, dropped : dict) -> None:
    """Keep the visibility of groups a step emptied (see dropEmptiedGroups)."""
    record = getattr(series, "emptied_group_viz", None)
    if record is None:
        record = series.emptied_group_viz = {}
    record.update(dropped)


class SectionStates():

    def __init__(self, section : Section = None, series : Series = None):
        """Create the section state manager.
        
            Params:
                section (Section): the section object to store states for
                series (Series): the series that contains the sections
        """
        self.initialized = False
        self.current_state = None
        self.undo_states = []
        self.redo_states = []
        # name -> alignment pin, for each object the last undo or redo
        # recreated (see recreatedAlignments)
        self.restored_alignments = {}
        if section and series:
            self.initialize(section, series)
    
    def initialize(self, section : Section, series : Series):
        """Create the section state manager.
        
            Params:
                section (Section): the section object to store states for
                series (Series): the series that contains the sections
        """
        # The welcome series' "hidden dir" is the bundled assets directory, not a
        # working copy: the app opens it in place from the install tree. Writing
        # an undo baseline there writes into the installation itself, which in a
        # source checkout modifies a tracked file (welcome.0.s0 goes from "{}" to
        # a copy of welcome.0) and on a read-only install either fails or, worse,
        # trips the OSError cleanup below into deleting the bundled file. Nothing
        # about the welcome series is meant to persist -- Series.save,
        # Section.save and Series.setOption all no-op for it, and Save/Save As
        # are disabled in the menus -- so keep its baseline in memory. It holds a
        # single section with no contours, so there is nothing to gain from the
        # file path anyway.
        if series.isWelcomeSeries():
            contours_fp = None
        else:
            contours_fp = os.path.join(series.hidden_dir, f"{series.sections[section.n]}.s0")
        # When the section is unmodified since it was loaded from disk (the
        # case for every initialize() on the hot paths: series-wide object
        # operations and section navigation both load a section and initialize
        # it immediately), its on-disk file equals this baseline, so copy the
        # file instead of re-serializing all contours. Fall back to serializing
        # the in-memory contours when the section is dirty (rare, e.g. a
        # b-section with unsaved edits re-initialized on save-as).
        section_clean = not (
            section.getAllModifiedNames()
            or section.tformsModified()
            or section.flags_modified
        )
        self.current_state = FieldState(
            section.contours,
            series.ztraces,
            section.tforms,
            section.flags,
            contours_fp,
            src_fp=(section.filepath if section_clean else None)
        )
        self.current_state.oids = captureObjectIds(
            series, section, section.contours
        )
        self.initialized = True
    
    def addState(self, section : Section, series : Series):
        """Add a new undo state (called when an action is performed).
        
            Params:
                section (Section): the section object
        """
        # clear redo states
        self.redo_states = []
        # push current state to undo states
        self.current_state.updateTime()  # keep track of when added to undos
        self.undo_states.append(self.current_state)
        # get the names of the updated contours
        updated_contours = section.getAllModifiedNames()
        # get the updated ztraces
        updated_ztraces = series.modified_ztraces.copy()
        # set the new current state
        self.current_state = FieldState(
            section.contours,
            series.ztraces,
            section.tforms,
            section.flags,
            None,
            updated_contours,
            updated_ztraces
        )
        self.current_state.obj_snapshot = objectSnapshot(series, updated_contours)
        self.current_state.oids = captureObjectIds(
            series, section, updated_contours, assign=True
        )
        
    def dropStatesAfter(self, count : int):
        """Drop the undo states pushed after the first `count`.

        Collapses a multi-part action into one undo step. The caller counts
        the undo states before triggering the follow-up parts (autoMerge does
        this around the merge that follows a draw, upstream issue #137) and
        the intermediate snapshots those parts pushed are removed, so the next
        undo lands on the state saved before the whole gesture rather than on
        a composite the user never saw. The current state is untouched: it
        already reflects the finished action, and redo replays it from there.

            Params:
                count (int): how many undo states to keep, from the oldest
        """
        del self.undo_states[count:]

    def undoState(self, section : Section, series : Series) -> set:
        """Restore an undo state on the section.
        
            Params:
                section (Section): the section to restore
                series (Series): the series with ztraces to restore
            Returns:
                (set): the names of modified contours
        """
        return self._restoreState(section, series, redo=False)

    def redoState(self, section : Section, series : Series) -> set:
        """Restore a redo state on the section.
        
            Params:
                section (Section): the section to restore
            Returns:
                (set): the names of modified contours
        """
        return self._restoreState(section, series, redo=True)

    def _restoreState(self, section : Section, series : Series, redo : bool):
        """Move the section one step back (undo) or forward (redo).

        Undo and redo differ only in where the traces and z-traces come from
        (`_restoreUndoTraces`, `_restoreRedoTraces`) and in which way the
        stacks turn. Everything else is this one routine, so a fix to the
        logging, transforms, flags, modified names or the store resync reaches
        both directions at once.

            Params:
                section (Section): the section to restore
                series (Series): the series with ztraces to restore
                redo (bool): True to redo, False to undo
        """
        if redo:
            source, destination = self.redo_states, self.undo_states
        else:
            source, destination = self.undo_states, self.redo_states
        if len(source) == 0:
            return
        # the state being returned to: its transforms and flags are restored
        # whole, whichever branch restored the traces
        target_state = source[-1]

        if redo:
            modified_contours, modified_ztraces = self._restoreRedoTraces(
                target_state, section, series
            )
        else:
            modified_contours, modified_ztraces = self._restoreUndoTraces(
                section, series
            )

        # update the series log
        for cname in modified_contours:
            series.addLog(cname, section.n, "Modify trace(s)")
        for zname in modified_ztraces:
            series.addLog(zname, section.n, "Modify ztrace")

        # restore the transforms
        section.tforms = target_state.getTforms()
        if section.tformsModified():
            series.addLog(None, section.n, "Modify transform")

        # restore the flags
        restored_flags = target_state.getFlags()
        # check if flag changes should be logged
        flist_1 = [len(f.comments) for f in section.flags]
        flist_2 = [len(f.comments) for f in restored_flags]
        if flist_1 != flist_2:
            series.addLog(None, section.n, "Modify flag(s)")
        section.flags = restored_flags

        # edit the undo/redo stacks and the current state
        # stamped as it goes onto the stack, the same way addState stamps the
        # state it pushes: favor3D compares these times to pick which undo a
        # Ctrl+Z takes, so a state arriving on a stack unstamped would be
        # compared on a birth time that has nothing to do with this undo
        self.current_state.updateTime()
        destination.append(self.current_state)
        # undo makes a copy of the state it lands on; redo uses the state itself
        popped = source.pop()
        self.current_state = popped if redo else popped.copy()

        # add the modified contours to the section object
        section.modified_contours = section.modified_contours.union(modified_contours)
        # add modified ztrace names to the series object
        series.modified_ztraces = series.modified_ztraces.union(modified_ztraces)

        # An undo or redo replaces the section's contours from outside
        # `Section`, either the whole dict at once or one key at a time, so
        # there is no sequence of row operations for the columnar store's
        # mutation hooks to have mirrored: the store is left describing exactly
        # the traces this restore just discarded, and its row map is keyed on
        # them. Rebuild it from the result. Not optional -- every `Section`
        # carries a store as of 2026-08-05, and without this the first edit
        # after an undo raises `ColumnarDualWriteMismatch` in the user's face.
        # D11's rebuild at `save()` does not cover this: the edit comes before
        # the save.
        section.resyncColumnarStore()

    def _restoreUndoTraces(self, section : Section, series : Series):
        """Put back the traces and z-traces the current state changed.

            Params:
                section (Section): the section to restore
                series (Series): the series with ztraces to restore
            Returns:
                (set, set): the names of the modified contours and ztraces
        """
        # objects this undo brings back from nothing get what they carried
        # when the action deleted them (see objectSnapshot). An object that
        # is in the series data, or still has a trace here, is left alone.
        existed = {
            n for n in self.current_state.getModifiedContours()
            if n in series.data["objects"] or len(section.contours.get(n, []))
        }

        # if only one undo state exists
        if len(self.undo_states) == 1:
            state = self.undo_states[0]
            # restore contours
            modified_contours = self.current_state.getModifiedContours()
            section.contours = state.getContours()
            restored_oids = getattr(state, "oids", {})
            # restore ztraces
            modified_ztraces = self.current_state.getModifiedZtraces()
            for zname in modified_ztraces:
                # A z-trace created AFTER this section's states were
                # initialized is absent from the initial snapshot (series-
                # level creation never calls addState), and indexing it here
                # raised KeyError on the user's first Ctrl+Z instead of
                # undoing (found 2026-08-28). The multi-state branch below
                # already tolerates the missing name; this branch matches it.
                if zname not in state.ztraces:
                    continue
                series.ztraces[zname] = restoreZtraceOnSection(
                    series.ztraces[zname],
                    state.ztraces[zname],
                    section.n
                )

        # if there are multiple undo states
        else:
            # iterate backwards and find the last ieration of the recently changed contours
            last_changed_contours = self.current_state.getModifiedContours().copy()
            last_changed_ztraces = self.current_state.getModifiedZtraces().copy()
            modified_contours = last_changed_contours.copy()
            modified_ztraces = last_changed_ztraces.copy()
            # each contour's id comes from the state its traces come from
            restored_oids = {}
            for state in reversed(self.undo_states):
                state_contours = state.getContours()
                state_ztraces = state.getZtraces()
                for contour in last_changed_contours.copy():
                    if contour in state_contours:
                        section.contours[contour] = state_contours[contour]
                        state_oids = getattr(state, "oids", {})
                        if contour in state_oids:
                            restored_oids[contour] = state_oids[contour]
                        last_changed_contours.remove(contour)
                for ztrace in last_changed_ztraces.copy():
                    if ztrace in state_ztraces:
                        series.ztraces[ztrace] = restoreZtraceOnSection(
                            series.ztraces[ztrace],
                            state_ztraces[ztrace],
                            section.n
                        )
                        last_changed_ztraces.remove(ztrace)
                if not last_changed_contours and not last_changed_ztraces:
                    break
            # if the contour was not found (aka it was just created)
            if last_changed_contours:
                for contour in last_changed_contours:
                    section.contours[contour] = Contour(contour)

        restoreObjectIds(series, section, modified_contours, restored_oids)

        recreated = [
            n for n in modified_contours
            if n not in existed and len(section.contours.get(n, []))
        ]
        snapshot = getattr(self.current_state, "obj_snapshot", {})
        restoreObjectSnapshot(
            series, snapshot, recreated,
            getattr(self.current_state, "undo_group_viz", None),
        )
        self.restored_alignments = recreatedAlignments(snapshot, recreated)

        return modified_contours, modified_ztraces

    def _restoreRedoTraces(self, redo_state : FieldState, section : Section, series : Series):
        """Put back the traces and z-traces a redo state holds.

            Params:
                redo_state (FieldState): the state being redone
                section (Section): the section to restore
                series (Series): the series with ztraces to restore
            Returns:
                (set, set): the names of the modified contours and ztraces
        """
        # restore the contours on the section
        state_contours = redo_state.getContours()
        modified_contours = redo_state.getModifiedContours()
        existed = {n for n in state_contours if n in series.data["objects"]}
        for contour_name in state_contours:
            section.contours[contour_name] = state_contours[contour_name]
        restoreObjectIds(
            series, section, state_contours, getattr(redo_state, "oids", {})
        )
        # objects this redo brings back from nothing get their attributes and
        # groups back too (see objectSnapshot)
        recreated = [
            n for n in state_contours
            if n not in existed and len(state_contours[n])
        ]
        snapshot = getattr(redo_state, "obj_snapshot", {})
        restoreObjectSnapshot(
            series, snapshot, recreated,
            getattr(redo_state, "group_viz", None),
        )
        self.restored_alignments = recreatedAlignments(snapshot, recreated)
        # restore the ztraces
        state_ztraces = redo_state.getZtraces()
        modified_ztraces = redo_state.getModifiedZtraces()
        for zname in state_ztraces:
            series.ztraces[zname] = restoreZtraceOnSection(
                series.ztraces[zname],
                state_ztraces[zname],
                section.n
            )

        return modified_contours, modified_ztraces

def restoreZtraceOnSection(orig_ztrace : Ztrace, new_ztrace : Ztrace, snum : int) -> Ztrace:
    """Restore the ztrace for a specific section.
    
        Params:
            orig_ztrace (Ztrace): the ztrace to be modified
            new_ztrace (Ztrace): the ztrace with data to be imported
            snum (int): the section number
        Returns:
            (Ztrace): the newly formed ztrace
    """
    orig_points = orig_ztrace.points.copy()
    new_points = new_ztrace.points.copy()
    restored_points = []
    for p0, p1 in zip(orig_points, new_points):
        if p1[2] == snum:
            restored_points.append(p1)
        else:
            restored_points.append(p0)
    return Ztrace(
        orig_ztrace.name,
        orig_ztrace.color,
        restored_points
    )

def applyColumnChange(trace, remove=None, add=None) -> bool:
    """Change one custom column value on a palette button, only if the button
    still holds what the change expects.

        Params:
            trace (Trace): the palette button's trace
            remove (tuple): (column, value) to take off, or None
            add (tuple): (column, value) to put on, or None
        Returns:
            (bool): False, touching nothing, if the button was edited since
    """
    defaults = copyObjDefaults(getattr(trace, "obj_defaults", None)) or {}
    columns = dict(defaults.get("user_columns", {}))
    if remove is not None and columns.get(remove[0]) != remove[1]:
        return False
    if add is not None and add[0] in columns and columns[add[0]] != add[1]:
        return False
    if remove is not None:
        del columns[remove[0]]
    if add is not None:
        columns[add[0]] = add[1]
    defaults["user_columns"] = columns
    trace.obj_defaults = copyObjDefaults(defaults)
    return True


class SeriesState():

    def __init__(self, breakable=True):
        """Create a single series state."""
        self.time = nextStamp()  # keep track of order
        self.undo_lens = {}  # keep track of individial section undos (these will be populated as the enumerateSections loop progresses)
        self.series_attrs = {}
        self.breakable = breakable
        # section number : the section's bc_profiles before this state's action.
        # Populated only by an action that rewrites bc_profiles, which is why it
        # does not live in FieldState alongside tforms and flags: see
        # recordBCProfiles.
        self.bc_profiles = {}
        # Button values a custom column edit changed (recordPaletteChanges);
        # empty for every other kind of series state.
        self.palette_changes = []
        self.palette_changes_applied = True
        # section number : the section's mag before this state's action.
        # Populated only by a magnification change (FieldWidget.setMag).
        self.mags = {}

    def recordMag(self, snum : int, mag : float):
        """Store a section's mag as it was before the action.

        Kept here and not in FieldState for the reason bc_profiles is: only a
        magnification change rewrites it. The traces, tforms, flags and
        z-traces come back through the section's own states, which
        FieldWidget.setMag records for every section.

            Params:
                snum (int): the section number
                mag (float): the section's mag
        """
        if snum not in self.mags:
            self.mags[snum] = mag

    def swapMag(self, section : Section) -> bool:
        """Exchange a section's mag with the stored one.

        Only the number: the section's own undo or redo puts back the traces,
        tforms and flags from the states it stored. Scaling them back instead
        would not be exact, because the section file rounds every point.

            Params:
                section (Section): the section to restore
            Returns:
                (bool): True if this state had a mag stored for the section
        """
        if section.n not in self.mags:
            return False
        stored = self.mags[section.n]
        self.mags[section.n] = section.mag
        section.mag = stored
        return True

    def recordPaletteChanges(self, changes : list):
        """Keep the button values a custom column edit changed, to reverse on
        undo and reapply on redo. Only those values: palette button edits
        make no undo state of their own, so anything wider would roll back a
        button edit made after this one."""
        self.palette_changes = list(changes)
        self.palette_changes_applied = True

    def swapPaletteChanges(self, series : Series):
        """Undo or redo the recorded button changes, whichever is due. Each
        change names a button by its place in the palette, looked up now."""
        if not getattr(self, "palette_changes", None):
            return

        tokens = getattr(series, "palette_tokens", {})
        by_token = {token: name for name, token in tokens.items()}

        def button(token, index):
            """The button at this place in the palette the change was made
            in, found by token so a renamed tab still matches and a new
            palette under the old name does not."""
            name = by_token.get(token)
            palette = series.palette_traces.get(name, []) if name else []
            return palette[index] if 0 <= index < len(palette) else None

        if self.palette_changes_applied:
            for token, index, before, after in reversed(self.palette_changes):
                trace = button(token, index)
                if trace is not None:
                    applyColumnChange(trace, remove=after, add=before)
        else:
            for token, index, before, after in self.palette_changes:
                trace = button(token, index)
                if trace is not None:
                    applyColumnChange(trace, remove=before, add=after)
        self.palette_changes_applied = not self.palette_changes_applied

    def recordBCProfiles(self, snum : int, bc_profiles : dict):
        """Store a section's brightness/contrast profiles as they were before the action.

        Kept on the series state rather than in FieldState, deliberately.
        FieldState is captured for every per-section undo, and
        brightness/contrast is the one piece of section data the app does not
        treat as undoable: FieldWidget.setBrightness and setContrast change it
        without calling saveState(), and MainWindow.optimizeBC gates itself
        behind noUndoWarning(). Storing bc_profiles in FieldState would
        therefore make an unrelated undo (say, of a trace drawn after the
        slider was moved) silently roll the user's brightness back, which is a
        worse bug than the one being fixed. Recording only for the actions that
        actually rewrite the profiles keeps the restore exact and leaves every
        other undo alone.

            Params:
                snum (int): the section number
                bc_profiles (dict): profile name : (brightness, contrast)
        """
        if snum not in self.bc_profiles:
            self.bc_profiles[snum] = deepcopy(bc_profiles)

    def swapBCProfiles(self, section : Section) -> bool:
        """Exchange a section's brightness/contrast profiles with the stored ones.

        An exchange rather than a one-way restore, so that undo and redo are the
        same operation, exactly as applySeriesAttributes does for the series
        attributes.

            Params:
                section (Section): the section to restore
            Returns:
                (bool): True if this state had profiles stored for the section
        """
        if section.n not in self.bc_profiles:
            return False
        stored = self.bc_profiles[section.n]
        self.bc_profiles[section.n] = deepcopy(section.bc_profiles)
        section.bc_profiles = stored
        return True
    
    # STATIC METHOD
    def getSeriesAttributes(series : Series):
        """Reset the stored series attributes.
        
            Params:
                series (Series): the series to store attributes for
        """
        obj_attrs = deepcopy(series.obj_attrs)
        ztrace_attrs = deepcopy(series.ztrace_attrs)
        
        object_groups = series.object_groups.copy()
        ztrace_groups = series.ztrace_groups.copy()

        alignment = series.alignment

        # the current brightness/contrast profile, for the same reason the
        # current alignment is stored: Series.modifyBCProfiles can rename or
        # delete the profile the series is displaying, and Section.brightness
        # indexes bc_profiles by this name, so an undo that restored the old
        # profile names without restoring the selected one would leave
        # series.bc_profile pointing at a key that no longer exists
        bc_profile = series.bc_profile

        ztraces = deepcopy(series.ztraces)

        user_columns = deepcopy(series.user_columns)
        object_columns = deepcopy(series.getOption("object_columns"))

        host_tree = series.host_tree.copy()

        # kept only to give a group the undo brings back the visibility it had:
        # removing the last object from a group deletes its entry, and the
        # Groups menu lists groups from these keys
        groups_visibility = dict(series.groups_visibility)
        
        return {
            "obj_attrs" : obj_attrs,
            "ztrace_attrs" : ztrace_attrs,
            "object_groups" : object_groups,
            "ztrace_groups" : ztrace_groups,
            "alignment" : alignment,
            "bc_profile" : bc_profile,
            "ztraces" : ztraces,
            "user_columns": user_columns,
            "object_columns": object_columns,
            "host_tree": host_tree,
            "groups_visibility": groups_visibility,
        }
    
    def resetSeriesAttributes(self, series : Series):
        """Reset the stored series attributes.
        
            Params:
                series (Series): the series to store attributes for
        """
        self.series_attrs = SeriesState.getSeriesAttributes(series)
    
    def applySeriesAttributes(self, series : Series, pre_series_attrs : dict):
        """Apply the stored series attributes to a series.
        
            Params:
                series (Series): the series to apply attributes to
                pre_series_attrs (dict): the series attributes to keep for the
                    opposite step (getSeriesAttributes), captured before the
                    sections were restored
        """
        self.swapPaletteChanges(series)
        for attr, value in self.series_attrs.items():
            if attr == "object_columns":
                continue  # only replace obj columns under specific circumstances (below)
            if attr == "groups_visibility":
                continue  # only fills in missing entries (below)
            setattr(series, attr, value)

        # a group the step brings back gets the visibility it had when the
        # state was made, or shown for a group with no entry then. Entries
        # already present are left alone, so a toggle made since stays.
        stored_viz = self.series_attrs["groups_visibility"]
        for group in series.object_groups.getGroupList():
            if group not in series.groups_visibility:
                series.groups_visibility[group] = stored_viz.get(group, True)

        # a group the step removes loses its entry, as removing its last
        # object does, or the Groups menu keeps a row for it. pre_series_attrs
        # still holds the entry, so the opposite step brings the value back.
        removed_groups = (
            set(pre_series_attrs["object_groups"].getGroupList()) -
            set(series.object_groups.getGroupList())
        )
        dropped = {}
        for group in removed_groups:
            if group in series.groups_visibility:
                dropped[group] = series.groups_visibility.pop(group)
        # kept for a later section step that brings the group back
        recordEmptiedGroups(series, dropped)

        # specific case: no sections modified but the series data needs to be refreshed bc preferred alignments changed
        if not self.undo_lens and alignmentPreferencesChanged(pre_series_attrs, self.series_attrs):
            series.data.refresh()
        
        # specific case: switch to previous obj_columns if user_columns has been changed
        if self.series_attrs["user_columns"] != pre_series_attrs["user_columns"]:
            series.setOption("object_columns", self.series_attrs["object_columns"])

        self.series_attrs = pre_series_attrs

def getAlignment(attrs, name):
    if name in attrs and "alignment" in attrs[name]:
        return attrs[name]["alignment"]
    else:
        return None

def alignmentPreferencesChanged(pre_series_attrs, post_series_attrs):
    """Check if the alignment preferences for objects and ztraces has changed."""
    pre_obj_attrs = pre_series_attrs["obj_attrs"]
    post_obj_attrs = post_series_attrs["obj_attrs"]
    pre_ztrace_attrs = pre_series_attrs["ztrace_attrs"]
    post_ztrace_attrs = post_series_attrs["ztrace_attrs"]

    for pre, post in (
        (pre_obj_attrs, post_obj_attrs),
        (pre_ztrace_attrs, post_ztrace_attrs)
    ):
        for name in set(pre.keys()).union(post.keys()):
            if getAlignment(pre, name) != getAlignment(post, name):
                return True
    
    return False


class SeriesStates():

    def __init__(self, series : Series):
        """Create the object to contain section states and information for series-wide states.
        
            Params:
                section_numbers (list): the list of section numbers in the series
        """
        self.series = series
        self.section_states_dict : dict[int, SectionStates] = {}
        for snum in self.series.sections:
            self.section_states_dict[snum] = SectionStates()
        self.undos : list[SeriesState] = []
        self.redos : list[SeriesState] = []
        # the visibility record of emptied groups belongs to this history,
        # and so does the record of dropped host links
        self.series.emptied_group_viz = {}
        self.series.dropped_host_links = set()
    
    def __iter__(self):
        """Return the iterator object for the series states"""
        return self.section_states_dict.__iter__()
    
    def __getitem__(self, index):
        """Allow the user to index the series states."""
        if type(index) is int:
            return self.section_states_dict[index]
        elif type(index) is Section:
            section_states = self.section_states_dict[index.n]
            if not section_states.initialized:
                section_states.initialize(index, self.series)
            return section_states
    
    def __len__(self):
        """Get the length of the series states."""
        return len(self.section_states_dict)

    def addState(self, breakable=True):
        """Create a new series undo state.
        
            Params:
                breakable (bool): True if series state can be broken (aka dissolved and left as individual section events)
        """
        # A new action ends every redo, series and section alike. A series
        # redo left in place replays its whole snapshot of groups, attributes
        # and z-traces over whatever the user did since, and a section redo can
        # name a z-trace this action deletes or renames, which made the redo
        # raise KeyError halfway through.
        self.redos = []
        for states in self.section_states_dict.values():
            states.redo_states = []
        new_state = SeriesState(breakable)
        new_state.resetSeriesAttributes(self.series)
        new_state.objects_before = set(self.series.data["objects"])
        self.undos.append(new_state)
    
    def recordBCProfiles(self, snum : int, bc_profiles : dict):
        """Store a section's brightness/contrast profiles on the newest series state.

        Called by the series-wide operations that rewrite bc_profiles, from
        inside their enumerateSections loop, before the section is modified.
        Rewriting bc_profiles trips none of the trackers SeriesIterator checks
        (getAllModifiedNames, tformsModified, flags_modified), so such a section
        never gets a per-section undo state and the profiles have to be carried
        by the series state itself.

            Params:
                snum (int): the section number
                bc_profiles (dict): profile name : (brightness, contrast)
        """
        if self.undos:
            self.undos[-1].recordBCProfiles(snum, bc_profiles)

    def recordMag(self, snum : int, mag : float):
        """Store a section's mag on the newest series state (SeriesState.recordMag).

            Params:
                snum (int): the section number
                mag (float): the section's mag before the change
        """
        if self.undos:
            self.undos[-1].recordMag(snum, mag)

    def recordPaletteChanges(self, changes : list):
        """Attach the button values a custom column edit changed to the
        newest series state. Called right after the edit."""
        if self.undos and changes:
            self.undos[-1].recordPaletteChanges(changes)

    def addSectionUndo(self, snum : int):
        """Flag the section's latest undo state as part of the most recent series undo.
        
            Params:
                snum (int): the section number
        """
        self.undos[-1].undo_lens[snum] = len(self[snum].undo_states)

        # the action saved the section before its state was added, so an
        # object the save deleted had already lost its attributes, groups and
        # hosts, and a rename has already moved an object's hosts to the new
        # name. So each object the action took off this section gets its copy
        # from the series state, taken before the action. Only an undo reads
        # that copy: a redo brings back only objects with traces here.
        state = self[snum].current_state
        objects = self.series.data["objects"]
        names = [
            n for n in state.getModifiedContours()
            if n not in objects or snum not in objects[n].traces
        ]
        if names:
            for name in names:
                state.obj_snapshot.pop(name, None)
            state.obj_snapshot.update(objectSnapshot(
                self.series, names, self.undos[-1].series_attrs
            ))

        # an object the action created (a rename to a deleted object's name)
        # does not take the links that deleted object had
        before = getattr(self.undos[-1], "objects_before", None)
        if before is not None:
            forgetHostLinks(self.series, {
                n for n in state.getModifiedContours()
                if n not in before and n in self.series.data["objects"]
            })

    def clear(self):
        """Clear all state tracking."""
        for snum in self.section_states_dict:
            self.section_states_dict[snum] = SectionStates()
        self.undos = []
        self.redos = []
        self.series.emptied_group_viz = {}
        self.series.dropped_host_links = set()
    
    def canUndo(self, current_section : int = None, redo=False):
        """Checks if an undo is possible.
        
            Params:
                current_section (int): the section the user is on
            Returns:
                (3D undo possible, 2D undo possible, 3D and 2D undo are linked)
        """
        if current_section is None:
            current_section = self.series.current_section
        if current_section not in self.section_states_dict:
            return (False, False, False)
        
        series_states = self.redos if redo else self.undos
        cs_undos = self[current_section].undo_states
        cs_redos = self[current_section].redo_states
        # neither section nor series undo is populated
        if not series_states and (
            redo and not cs_redos or
            not redo and not cs_undos
        ):
            return (False, False, False)
        # only section undo populated
        elif not series_states:
            return (False, True, False)
        # series undo is populated
        elif series_states:
            undo_lens = series_states[-1].undo_lens
            # check if state numbers match on all sections
            all_sections_match = True
            for snum, undo_len in undo_lens.items():
                states = self[snum]
                if not states.initialized or len(states.undo_states) != undo_len - (1 if redo else 0):
                    all_sections_match = False
                    break
            # check if state numbers match on the current section
            current_section_match = bool(
                current_section in undo_lens and 
                len(cs_undos) == undo_lens[current_section] - (1 if redo else 0)
            )
            # check if 2D undo is part of any unbreakable set
            is_in_unbreakable = False
            for state in series_states:
                if (
                    not state.breakable and
                    current_section in state.undo_lens and 
                    len(cs_undos) == state.undo_lens[current_section] - (1 if redo else 0)
                ):
                    is_in_unbreakable = True
                    break
            # check if user can perform a 2D undo only
            can_2D = bool(
                not is_in_unbreakable and
                (
                    not redo and cs_undos or
                    redo and cs_redos
                )  # no link to unbreakable set and section has undo states
            )
            return (all_sections_match, can_2D, current_section_match)
    
    def favor3D(self, current_section : int = None, redo=False):
        """If both a 2D and 3D undo are possible and they are not linked, check which one was done more recently.
        Return True if 3D is more recent (and should be favored)."""
        if current_section is None:
            current_section = self.series.current_section
        
        can_3D, can_2D, linked = self.canUndo(current_section, redo)
        if can_3D and can_2D and not linked:
            if redo:
                state_3D = self.redos[-1]
                state_2D = self[current_section].redo_states[-1]
            else:
                state_3D = self.undos[-1]
                state_2D = self[current_section].undo_states[-1]
            if state_3D.time > state_2D.time:
                return True
            else:
                return False
        else:
            return None
    
    def undoState(self, redo=False):
        """Perform a series-wide undo or redo.
        
            Params:
                redo (bool): True if redo should be performed instead of undo
        """
        can_3D, can_2D, linked = self.canUndo(redo=redo)
        
        if not can_3D:
            return
        
        state = self.redos[-1] if redo else self.undos[-1]

        # what the opposite step puts back, captured before any section is
        # restored: restoring a section can delete an object (undoing a partial
        # rename deletes the new one), and that clears its attributes, groups
        # and hosts, so a snapshot taken afterward would redo without them
        pre_series_attrs = SeriesState.getSeriesAttributes(self.series)
        
        # undo/redo the inidividual sections. A section can be in this set for
        # either of two reasons: it has a per-section undo state belonging to
        # this series state (undo_lens), or the action rewrote its
        # brightness/contrast profiles, which SeriesIterator cannot detect and
        # so records here instead (bc_profiles).
        sections = set(state.undo_lens.keys()) | set(state.bc_profiles.keys())
        if sections:
            # writes_after: the series attributes below are the other half
            # of this step, so a series closed at the last update stops it
            # with an error rather than ending it as done
            for snum, section in self.series.enumerateSections(
                message=("Re" if redo else "Un") + "doing action...",
                writes_after=True,
            ):
                if snum not in sections:
                    continue
                # the mag only; the section's own step puts back its traces
                state.swapMag(section)
                if snum in state.undo_lens:
                    states = self[snum]
                    if redo:
                        states.redoState(section, self.series)
                    else:
                        states.undoState(section, self.series)
                state.swapBCProfiles(section)
                section.save()
        
        # undo/redo the series attributes
        state.applySeriesAttributes(self.series, pre_series_attrs)

        # move the state accordingly, stamped as it goes onto the other stack
        # the way SectionStates stamps its states: favor3D compares these
        # stamps with the section's, so a series state still carrying the stamp
        # it was first made with would lose to any section step undone before
        # it, and redo would replay the two in the wrong order
        state.time = nextStamp()
        if redo:
            self.undos.append(self.redos.pop())
        else:
            self.redos.append(self.undos.pop())
        
    def undoSection(self, section : Section, redo=False):
        """Undo/redo on a section
        
            Params:
                section (Section): the section to undo/redo on
                redo (bool): True if redo, False if undo
        """
        can_3D, can_2D, linked = self.canUndo(redo=redo)
        
        if not can_2D:
            return
        
        # check if series undo/redo should be broken
        snum = section.n
        if redo: states = self.redos
        else: states = self.undos
        for state in states.copy():
            if (
                section.n in state.undo_lens and (
                    len(self[snum].undo_states) == state.undo_lens[snum] - (1 if redo else 0)
                )
            ):
                if state.breakable:
                    states.remove(state)
                else:
                    return # do not continue if state is unbreakable
                
        if redo:
            self.section_states_dict[section.n].redoState(section, self.series)
        else:
            self.section_states_dict[section.n].undoState(section, self.series)

    def checkOverwrite(self, snum : int):
        """Check if a series undo/redo should be removed.
        
        (Called after a state has just been written to the given section)
        
            Params:
                snum (int): the section number to check
        """
        # check if a series undo has been overwritten
        if self.undos and snum in self.undos[-1].undo_lens:
            if self.undos[-1].undo_lens[snum] == len(self[snum].undo_states):
                self.undos.pop()
        # a new section action ends every series redo, not only the ones that
        # touched this section: a series redo restores the series attributes
        # whole, so one from before this action would overwrite it. The
        # per-section parts of those redos go with them, so none is left to be
        # redone alone on its section (which an unbreakable set forbids).
        for redo in self.redos:
            for other in redo.undo_lens:
                if other in self.section_states_dict:
                    self.section_states_dict[other].redo_states = []
        self.redos = []

    






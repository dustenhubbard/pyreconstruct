"""In-memory object ids.

An object is a name, and a name can be reused: delete H, draw a new H, and
nothing in the series data tells the two apart. Undo needs to. An object id is
an integer that stands for one object for as long as it has traces, the way a
palette token stands for one palette (`Series.paletteToken`).

The rules:

1. An id keeps one name for life.
2. A (section, name) that gets traces takes the name's live id, or a fresh one
   if the name has none. A deleted name that is drawn again gets a fresh id.
   The exception is an object that lost its traces some other way than being
   deleted (its sections were deleted, or an import emptied it): its id is
   parked, and the name's next traces take it back (see drop).
3. Undo and redo put back the id each restored set of traces had
   (`FieldState.oids`).
4. An id is live while it has traces on any section.

Ids are kept per (section, name) and not per name, because an undo on one
section can bring back the old H while a new H lives on another.

Never saved: a loaded series gives each name one fresh id, and undo history,
the only thing that can bring a dead id back, does not outlive the session.
"""

import itertools


class ObjectIds():

    def __init__(self):
        """Create an empty id registry."""
        self._counter = itertools.count(1)
        # (section number, name) -> id, for each name with traces there
        self.placed : dict[tuple[int, str], int] = {}
        # id -> its name, for every id ever issued (rule 1)
        self.name_of : dict[int, str] = {}
        # name -> an id held for a name with no traces (see reserve)
        self.unplaced : dict[str, int] = {}
        # name -> ids that lost their last trace without the object being
        # deleted (see drop); still visible, and taken back by the name
        self.parked : dict[str, set[int]] = {}
        # name -> ids an undo just parked again; the object delete the same
        # step saves leaves them parked (see restoreParked, endStep)
        self._kept : dict[str, set[int]] = {}
        # name -> {live id: how many sections it is placed on}
        self._live : dict[str, dict[int, int]] = {}
        # ids a reader (HostTree) built something from, and a counter that
        # changes whenever one of them becomes visible or stops being
        # visible (see visible), so the reader can tell when it is stale
        self.watched : set[int] = set()
        self.version = 0

    def _new(self, name : str) -> int:
        oid = next(self._counter)
        self.name_of[oid] = name
        return oid

    def _attach(self, snum : int, name : str, oid : int):
        self.placed[(snum, name)] = oid
        counts = self._live.setdefault(name, {})
        counts[oid] = counts.get(oid, 0) + 1

    def _detach(self, snum : int, name : str):
        oid = self.placed.pop((snum, name), None)
        if oid is None:
            return
        counts = self._live[name]
        counts[oid] -= 1
        if not counts[oid]:
            del counts[oid]
            if not counts:
                del self._live[name]

    def _settle(self, before : dict):
        """Count a change for each watched id whose visibility flipped.

            Params:
                before (dict): id -> whether it was visible before the change
        """
        for oid, was in before.items():
            if oid in self.watched and self.visible(oid) != was:
                self.version += 1
                return

    def peek(self, snum : int, name : str):
        """The id of the name's traces on the section, or None."""
        return self.placed.get((snum, name))

    def live(self, name : str) -> set:
        """The ids with traces under the name, on any section."""
        return set(self._live.get(name, ()))

    def visible(self, oid : int) -> bool:
        """True while the id stands for an object the user can see: it has
        traces (live), it is held for a name with none (reserve), or it lost
        its traces without the object being deleted (parked). An id whose
        object was deleted is none of these until an undo brings it back."""
        name = self.name_of.get(oid)
        if name is None:
            return False
        return (
            oid in self._live.get(name, ())
            or self.unplaced.get(name) == oid
            or oid in self.parked.get(name, ())
        )

    def visibleIds(self, name : str) -> set:
        """The visible ids under the name."""
        oids = set(self._live.get(name, ()))
        if name in self.unplaced:
            oids.add(self.unplaced[name])
        oids |= self.parked.get(name, set())
        return oids

    def _unpark(self, name : str, oid : int):
        held = self.parked.get(name)
        if held and oid in held:
            held.discard(oid)
            if not held:
                del self.parked[name]

    def ensure(self, snum : int, name : str) -> int:
        """The id of the name's traces on the section, giving it one if it
        has none: the name's live id (the newest, if an undo left two), else
        the one reserved for the name, else its newest parked id, else a
        fresh one."""
        oid = self.placed.get((snum, name))
        if oid is not None:
            return oid
        counts = self._live.get(name)
        if counts:
            oid = max(counts)
        elif name in self.unplaced:
            # reserved to live: it stays visible
            oid = self.unplaced.pop(name)
        elif name in self.parked:
            # parked to live: it stays visible
            oid = max(self.parked[name])
            self._unpark(name, oid)
        else:
            oid = self._new(name)
        self._attach(snum, name, oid)
        return oid

    def place(self, snum : int, name : str, oid : int):
        """Put the name's traces on the section under a known id (undo and
        redo). Raises ValueError for an id this registry did not issue to
        the name."""
        if self.name_of.get(oid) != name:
            raise ValueError(f"object id {oid} does not belong to {name!r}")
        current = self.placed.get((snum, name))
        if current == oid:
            return
        before = {oid: self.visible(oid)}
        if current is not None:
            before[current] = self.visible(current)
        self._detach(snum, name)
        if self.unplaced.get(name) == oid:
            del self.unplaced[name]
        self._unpark(name, oid)
        self._attach(snum, name, oid)
        self._settle(before)

    def drop(self, snum : int, name : str, park : bool = False):
        """The name has no traces left on the section.

            Params:
                snum (int): the section number
                name (str): the object name
                park (bool): True if this is not a delete of the object (a
                    deleted section, an import, a refresh): an id left with
                    no traces is parked instead of going out of sight, so
                    the object keeps its links and the name's next traces
                    take it back
        """
        oid = self.placed.get((snum, name))
        if oid is None:
            return
        before = {oid: self.visible(oid)}
        self._detach(snum, name)
        if park and oid not in self._live.get(name, ()):
            self.parked.setdefault(name, set()).add(oid)
        self._settle(before)

    def reserve(self, name : str) -> int:
        """An id for the name without placing it: its live id, or one held
        in `unplaced` until the name gets traces (rule 2 takes it then)."""
        counts = self._live.get(name)
        if counts:
            return max(counts)
        if name not in self.unplaced and name in self.parked:
            return max(self.parked[name])
        if name not in self.unplaced:
            # a new id: nothing was built from it yet
            self.unplaced[name] = self._new(name)
        return self.unplaced[name]

    def release(self, name : str):
        """The object under the name was deleted: its reserved and parked ids
        go out of sight, except those the undo now being saved just parked
        again (restoreParked). Its live ids, if any, are untouched."""
        parked = self.parked.pop(name, set())
        kept = parked & self._kept.get(name, set())
        if kept:
            self.parked[name] = kept
        before = {oid: True for oid in parked - kept}
        oid = self.unplaced.pop(name, None)
        if oid is not None:
            before[oid] = True
        self._settle(before)

    def heldParked(self, names=None) -> dict:
        """A copy of the parked ids, for undo: name -> frozenset of ids.

            Params:
                names: the names to copy, or None for every name
        """
        if names is None:
            return {name: frozenset(held) for name, held in self.parked.items()}
        return {
            name: frozenset(self.parked[name]) for name in names
            if name in self.parked
        }

    def restoreParked(self, held : dict, names=None, keep=False):
        """Put the parked ids back as heldParked copied them. An id that has
        traces now stays live; an id parked now that the copy does not hold
        goes out of sight.

            Params:
                held (dict): what heldParked returned
                names: the names to restore, or None for every name
                keep (bool): True for a section undo: the save that follows
                    it deletes an object the undo emptied, and that delete
                    must not release what the undo just parked again
        """
        if names is None:
            names = set(held) | set(self.parked)
        before = {}
        for name in names:
            live = self._live.get(name, {})
            current = self.parked.get(name, set())
            target = {oid for oid in held.get(name, ()) if oid not in live}
            if target == current:
                continue
            for oid in current | target:
                before[oid] = self.visible(oid)
            if target:
                self.parked[name] = set(target)
            else:
                self.parked.pop(name, None)
        if keep:
            for name in names:
                if name in self.parked:
                    self._kept[name] = set(self.parked[name])
        self._settle(before)

    def endStep(self):
        """The series data has caught up with the step (SeriesData)."""
        self._kept.clear()

    def dropSection(self, snum : int):
        """The section was deleted: its traces' ids lose that placement."""
        for key in [k for k in self.placed if k[0] == snum]:
            self.drop(*key, park=True)

    def renumber(self, mapping : dict):
        """Move each placement to its section's new number.

        Called when sections are renumbered (Series.reorderSections), so
        every set of traces keeps the id it had, including when one name has
        two live ids on different sections.

            Params:
                mapping (dict): old section number -> new section number, for
                    every section the series has
            Raises:
                ValueError: before changing anything, if two sections would
                    take the same number or a placement is on a section the
                    mapping does not name (a deleted section must have gone
                    through dropSection first)
        """
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("two sections cannot take the same number")
        missing = {snum for snum, _ in self.placed if snum not in mapping}
        if missing:
            raise ValueError(f"no new number for section(s) {sorted(missing)}")
        self.placed = {
            (mapping[snum], name): oid
            for (snum, name), oid in self.placed.items()
        }

    def reconcile(self, present):
        """Match the placements to the (section, name) pairs that have
        traces after a full refresh of the series data.

        A pair that is already placed keeps its id. A pair that is not takes
        one by `ensure`, before anything is dropped, so a name with one live
        id keeps it. Then each placement with no traces left is dropped.
        Section numbers must already be current: a renumbering is carried by
        `renumber`, not guessed here.

            Params:
                present: the (section number, name) pairs that have traces
        """
        present = set(present)
        for snum, name in sorted(present - self.placed.keys()):
            self.ensure(snum, name)
        for key in [k for k in self.placed if k not in present]:
            self.drop(*key, park=True)

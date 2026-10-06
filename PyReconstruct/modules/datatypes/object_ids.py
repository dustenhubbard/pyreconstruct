"""In-memory object ids.

An object is a name, and a name can be reused: delete H, draw a new H, and
nothing in the series data tells the two apart. Undo needs to. An object id is
an integer that stands for one object for as long as it has traces, the way a
palette token stands for one palette (`Series.paletteToken`).

The rules:

1. An id keeps one name for life.
2. A (section, name) that gets traces takes the name's live id, or a fresh one
   if the name has none. A deleted name that is drawn again gets a fresh id.
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
        # name -> {live id: how many sections it is placed on}
        self._live : dict[str, dict[int, int]] = {}
        # changes whenever an id becomes visible or stops being visible
        # (see visible), so a reader can tell when what it built is stale
        self.version = 0

    def _new(self, name : str) -> int:
        oid = next(self._counter)
        self.name_of[oid] = name
        return oid

    def _attach(self, snum : int, name : str, oid : int):
        self.placed[(snum, name)] = oid
        counts = self._live.setdefault(name, {})
        if oid not in counts:
            self.version += 1
        counts[oid] = counts.get(oid, 0) + 1

    def _detach(self, snum : int, name : str):
        oid = self.placed.pop((snum, name), None)
        if oid is None:
            return
        counts = self._live[name]
        counts[oid] -= 1
        if not counts[oid]:
            self.version += 1
            del counts[oid]
            if not counts:
                del self._live[name]

    def peek(self, snum : int, name : str):
        """The id of the name's traces on the section, or None."""
        return self.placed.get((snum, name))

    def live(self, name : str) -> set:
        """The ids with traces under the name, on any section."""
        return set(self._live.get(name, ()))

    def visible(self, oid : int) -> bool:
        """True while the id stands for an object the user can see: it has
        traces (live), or it is held for a name with none (reserve). An id
        that lost its last trace is neither until an undo brings it back."""
        name = self.name_of.get(oid)
        return oid in self._live.get(name, ()) or self.unplaced.get(name) == oid

    def visibleIds(self, name : str) -> set:
        """The visible ids under the name."""
        oids = set(self._live.get(name, ()))
        if name in self.unplaced:
            oids.add(self.unplaced[name])
        return oids

    def ensure(self, snum : int, name : str) -> int:
        """The id of the name's traces on the section, giving it one if it
        has none: the name's live id (the newest, if an undo left two), else
        the one reserved for the name, else a fresh one."""
        oid = self.placed.get((snum, name))
        if oid is not None:
            return oid
        counts = self._live.get(name)
        if counts:
            oid = max(counts)
        elif name in self.unplaced:
            oid = self.unplaced.pop(name)
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
        if self.placed.get((snum, name)) == oid:
            return
        self._detach(snum, name)
        if self.unplaced.get(name) == oid:
            del self.unplaced[name]
        self._attach(snum, name, oid)

    def drop(self, snum : int, name : str):
        """The name has no traces left on the section."""
        self._detach(snum, name)

    def reserve(self, name : str) -> int:
        """An id for the name without placing it: its live id, or one held
        in `unplaced` until the name gets traces (rule 2 takes it then)."""
        counts = self._live.get(name)
        if counts:
            return max(counts)
        if name not in self.unplaced:
            self.unplaced[name] = self._new(name)
            self.version += 1
        return self.unplaced[name]

    def release(self, name : str):
        """The name's reserved id is no longer held: the object it stood for
        is gone. Its live ids, if any, are untouched."""
        if self.unplaced.pop(name, None) is not None:
            self.version += 1

    def dropSection(self, snum : int):
        """The section was deleted: its traces' ids lose that placement."""
        for key in [k for k in self.placed if k[0] == snum]:
            self._detach(*key)

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
            self._detach(*key)

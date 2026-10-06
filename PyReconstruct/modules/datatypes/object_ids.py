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

    def peek(self, snum : int, name : str):
        """The id of the name's traces on the section, or None."""
        return self.placed.get((snum, name))

    def live(self, name : str) -> set:
        """The ids with traces under the name, on any section."""
        return set(self._live.get(name, ()))

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
        return self.unplaced[name]

    def reconcile(self, present):
        """Match the placements to the (section, name) pairs that have
        traces: ensure each one first, then drop the rest, so a pair that
        moved (a renumbered section) keeps its name's id."""
        present = set(present)
        for snum, name in present:
            self.ensure(snum, name)
        for key in [k for k in self.placed if k not in present]:
            self._detach(*key)

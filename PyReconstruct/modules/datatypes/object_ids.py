"""In-memory object ids.

An object is a name, and a name can be reused: delete H, draw a new H, and
nothing in the series data tells the two apart. Undo needs to. An object id is
an integer that stands for one object for as long as it has traces, the way a
palette token stands for one palette (`Series.paletteToken`).

The rules:

1. An id keeps one name for life.
2. A (section, name) that gets traces takes the name's live id, or a fresh one
   if the name has none. A deleted name that is drawn again gets a fresh id.
   The exception is an id the host tree keeps for the name: an object that
   lost its traces some other way than being deleted (its sections were
   deleted, or an import emptied it) keeps its links, and the name's next
   traces take its id back (see drop, and HostTree.keptId).
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

    def __init__(self, series=None):
        """Create an empty id registry.

            Params:
                series (Series): the series whose host tree keeps the ids of
                    names with no traces (HostTree). None for a registry on
                    its own, which keeps none.
        """
        self._counter = itertools.count(1)
        # (section number, name) -> id, for each name with traces there
        self.placed : dict[tuple[int, str], int] = {}
        # id -> its name, for every id ever issued (rule 1)
        self.name_of : dict[int, str] = {}
        # name -> {live id: how many sections it is placed on}
        self._live : dict[str, dict[int, int]] = {}
        self.series = series
        # changes whenever an id gets its first trace or loses its last, so
        # a reader (HostTree) can tell when what it built from the ids is
        # stale
        self.version = 0

    def _tree(self):
        """The host tree that keeps ids for names with no traces, or None.

        A tree holds the ids of one registry for its life, the one its
        series had when the tree was built. A registry built beside it (a
        second SeriesData for the same series) has no tree to tell.
        """
        tree = getattr(self.series, "host_tree", None)
        if tree is None or not tree.holdsIds(self):
            return None
        return tree

    def issue(self, name : str) -> int:
        """A fresh id for the name, placed nowhere. The host tree issues one
        for a name that has links but no traces (HostTree.reserve)."""
        oid = next(self._counter)
        self.name_of[oid] = name
        return oid

    def _attach(self, snum : int, name : str, oid : int):
        self.placed[(snum, name)] = oid
        counts = self._live.setdefault(name, {})
        counts[oid] = counts.get(oid, 0) + 1
        if counts[oid] == 1:
            self.version += 1
            tree = self._tree()
            if tree is not None:
                tree.traced(oid)

    def _detach(self, snum : int, name : str) -> tuple:
        """Take the name's traces on the section off their id.

            Returns:
                (int, bool): the id, or None if nothing was placed there, and
                    True if that was the id's last trace
        """
        oid = self.placed.pop((snum, name), None)
        if oid is None:
            return None, False
        counts = self._live[name]
        counts[oid] -= 1
        if counts[oid]:
            return oid, False
        del counts[oid]
        if not counts:
            del self._live[name]
        self.version += 1
        return oid, True

    def peek(self, snum : int, name : str):
        """The id of the name's traces on the section, or None."""
        return self.placed.get((snum, name))

    def live(self, name : str) -> set:
        """The ids with traces under the name, on any section."""
        return set(self._live.get(name, ()))

    def isLive(self, oid : int) -> bool:
        """True while the id has traces on any section."""
        name = self.name_of.get(oid)
        return name is not None and oid in self._live.get(name, ())

    def ensure(self, snum : int, name : str) -> int:
        """The id of the name's traces on the section, giving it one if it
        has none: the name's live id (the newest, if an undo left two), else
        the id the host tree keeps for the name, else a fresh one."""
        oid = self.placed.get((snum, name))
        if oid is not None:
            return oid
        counts = self._live.get(name)
        if counts:
            oid = max(counts)
        else:
            tree = self._tree()
            oid = tree.keptId(name) if tree is not None else None
            if oid is None:
                oid = self.issue(name)
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
        self._attach(snum, name, oid)

    def drop(self, snum : int, name : str, keep : bool = False):
        """The name has no traces left on the section.

            Params:
                snum (int): the section number
                name (str): the object name
                keep (bool): True if this is not a delete of the object (a
                    deleted section, an import, a refresh): the host tree
                    keeps an id left with no traces, so the object keeps its
                    links and the name's next traces take the id back. False
                    for an object deleted outright: the tree lets go of every
                    id it kept for the name.
        """
        oid, last = self._detach(snum, name)
        if oid is None or not last:
            return
        tree = self._tree()
        if tree is None:
            return
        if keep:
            tree.keep(oid)
        else:
            tree.deleted(oid)

    def dropSection(self, snum : int):
        """The section was deleted: its traces' ids lose that placement, and
        the host tree keeps any left with no traces."""
        for key in [k for k in self.placed if k[0] == snum]:
            self.drop(*key, keep=True)

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
        id keeps it. Then each placement with no traces left is dropped, and
        the host tree keeps its id: a refresh deletes no object. Section
        numbers must already be current: a renumbering is carried by
        `renumber`, not guessed here.

            Params:
                present: the (section number, name) pairs that have traces
        """
        present = set(present)
        for snum, name in sorted(present - self.placed.keys()):
            self.ensure(snum, name)
        for key in [k for k in self.placed if k not in present]:
            self.drop(*key, keep=True)

import os
from typing import Optional

from .filters import passesFilters
from .object_ids import ObjectIds

class HostTree():
    """Which objects host which.

    A link joins two object ids (datatypes/object_ids.py), not two names, so
    it belongs to the objects that had those names when it was made. Deleting
    an object leaves its links in place but dormant: they show again if an
    undo brings that object back, and a new object that takes the old name
    does not get them.

    The tree also keeps the ids of objects that have links but no traces: a
    name a loaded file links to with no traces of its own, a host another
    series had, or an object emptied without being deleted (its sections
    deleted, an import). Their links stay on screen and in the file, and the
    name's next traces take the kept id back (ObjectIds.ensure). An object
    deleted outright takes the ids kept for its name out of sight until an
    undo. The kept ids are part of the tree's state, so a series undo's copy
    of the tree carries them, and a section undo puts back the ones its action
    changed (FieldState.kept_before).

    Callers still speak names. Reads go through a name projection of the
    links whose two ends are both visible (live or kept), rebuilt when the
    links or the ids change. When an undo brings an old object back while a
    new one has its name, the name shows the links of both.
    """

    # renames so far, in every tree: each numbers the kept ids it takes out
    # of sight, so an undo step can tell its own from an earlier one's
    # (SeriesState.renamed_out)
    renames = 0

    def __init__(self, host_dict : dict, series):
        """Create the HostTree from a dictionary of (obj_name, hosts)
        
            Params:
                host_dict (dict): the dictionary of (obj_name, hosts)
                series (Series): the series that contains the host tree
        """
        self.series = series
        ids = getattr(getattr(series, "data", None), "object_ids", None)
        # the registry whose ids the links join, for the life of the tree. A
        # tree with no series keeps its own ids; every name then holds a
        # kept id, and the tree behaves as a plain name tree
        self._ids = ids if ids is not None else ObjectIds()
        self._reset(set(), set())

        for obj_name, hosts in host_dict.items():
            self.add(obj_name, hosts)

    def _reset(self, edges : set, members : set, order : Optional[dict] = None,
               kept : Optional[dict] = None, renamed : Optional[dict] = None):
        # names in the order the tree has always listed them: added by
        # add() (the object, then its hosts), dropped by removeObject, and
        # moved to the end by a rename. Reads that walk the tree by name
        # (merge) depend on it.
        # name -> its place; places only grow, so the dict's order is theirs
        self._order : dict = {}
        self._next_place = 0
        self._register(order or ())
        # (traveler id, host id)
        self._edges : set[tuple[int, int]] = edges
        # ids registered by add() whether or not they have links, so a name
        # stays in the tree as it always has
        self._members : set[int] = members
        # name -> the ids kept visible for it while they have no traces (see
        # the class docstring)
        self._kept : dict[str, set[int]] = kept if kept is not None else {}
        # kept ids a rename took out of sight, until an undo keeps them again
        # or they get traces: id -> the rename's number (see renames)
        self._renamed : dict[int, int] = renamed if renamed is not None else {}
        # ids treated as gone while a rename runs (see renameObject)
        self._hidden : frozenset = frozenset()
        # the name projection: name -> {"hosts", "travelers"}, and the
        # visible links behind each name pair in it
        self._objects : dict = {}
        # the last place of a name in the projection: a new entry with a
        # later place can go in at the end without a rebuild (see _entry)
        self._last_place = -1
        self._pair_edges : dict = {}
        self._built = None
        self._stale = True
        # False when the projection had to refuse or trim a pair (two
        # objects under one name), so it is not just the visible links
        self._exact = False
        self._trimmed : list = []

    def holdsIds(self, ids) -> bool:
        """True if the links join the ids of this registry (ObjectIds._tree)."""
        return ids is self._ids

    # the ids kept for names without traces
    def visible(self, oid : int) -> bool:
        """True while the id stands for an object the user can see: it has
        traces, or the tree keeps it for a name with none."""
        return self._visible(oid)

    def visibleIds(self, name : str) -> set:
        """The visible ids under the name."""
        return self._visibleIds(name)

    def keptIds(self, name : str) -> set:
        """The ids kept for the name while they have no traces."""
        return set(self._kept.get(name, ()))

    def keptId(self, name : str):
        """The id the name's next traces take: the newest kept for it, or
        None (ObjectIds.ensure)."""
        return max(self.keptIds(name), default=None)

    def keep(self, oid : int):
        """Keep the id visible: its object lost its traces without being
        deleted (ObjectIds.drop)."""
        if self._ids.isLive(oid):
            return
        self._renamed.pop(oid, None)
        name = self._ids.name_of[oid]
        kept = self._kept.setdefault(name, set())
        if oid not in kept:
            kept.add(oid)
            self._stale = True

    def traced(self, oid : int):
        """The id has traces again (ObjectIds.ensure, place): it needs no
        keeping."""
        self._renamed.pop(oid, None)
        name = self._ids.name_of[oid]
        kept = self._kept.get(name)
        if kept and oid in kept:
            kept.discard(oid)
            if not kept:
                del self._kept[name]
            self._stale = True

    def deleted(self, oid : int):
        """The object with this id lost its last trace by a delete
        (ObjectIds.drop): the ids kept for its name go out of sight, until
        an undo keeps them again."""
        self._release(self._ids.name_of[oid])

    def _release(self, name : str):
        if self._kept.pop(name, None):
            self._stale = True

    def restoreKept(self, kept : dict):
        """Keep again the ids a section undo or redo puts back
        (FieldState.kept_before, kept_after), for the names its action
        changed. An id with traces now needs no keeping.

            Params:
                kept (dict): name -> the ids kept for it at that state
        """
        ids = self._ids
        for name, oids in kept.items():
            for oid in oids:
                if ids.name_of.get(oid) == name and not ids.isLive(oid):
                    self.keep(oid)

    def linksMadeSince(self, before, names) -> set:
        """The links this tree has and the tree before has not, with an end
        under one of the names.

            Params:
                before (HostTree): an earlier copy of this tree
                names: the object names
            Returns:
                (set): (traveler id, host id) for each such link
        """
        name_of = self._ids.name_of
        names = set(names)
        return {
            (t, h) for t, h in self._edges - before._edges
            if name_of.get(t) in names or name_of.get(h) in names
        }

    def linksTakenSince(self, before, names) -> set:
        """The links the tree before has and this tree has not, with an end
        under one of the names, whose traveler no longer has the host here.
        Those were replaced (a copy into a name that exists clears its hosts
        first); a link taken off only because the host became a host of
        another host (checkRedundantHosts) is not one of them.

            Params:
                before (HostTree): an earlier copy of this tree
                names: the object names
            Returns:
                (set): (traveler id, host id) for each such link
        """
        name_of = self._ids.name_of
        return {
            (t, h) for t, h in before.linksMadeSince(self, names)
            if name_of[h] not in self.getHosts(name_of[t], True)
        }

    def restoreLinks(self, links, taken=()):
        """Make again links a series undo took with its copy of the tree,
        as a section redo brings back the ids they join
        (FieldState.links_made), after taking away again the links its
        action took away for the same names (links_taken).

        A link that would make an object a host of itself, directly or
        through a chain, is refused as add() refuses it. The redo of one
        section replays only the links of its own names, so the action may
        have broken that chain on a section not redone yet (a copy clears
        the hosts of an existing name on the section it copies to).

            Params:
                links: (traveler id, host id) pairs
                taken: (traveler id, host id) pairs
        """
        self._removeEdges(set(taken))
        links = set(links)
        self._addMembers({oid for edge in links for oid in edge})
        for t, h in sorted(links):
            pair = self._pairOf(t, h)
            if pair is not None and pair[0] in self.getHosts(pair[1], True):
                continue
            self._addEdges({(t, h)})

    def renamedIds(self, first : int, last : int) -> set:
        """The kept ids still out of sight from the renames numbered first
        to last."""
        return {oid for oid, n in self._renamed.items() if first <= n <= last}

    def inheritKept(self, previous, out_of_sight=(), brought_back=()):
        """Take over what the tree this one replaces keeps, as a series undo
        or redo installs this copy (SeriesState.applySeriesAttributes).

        An object that lost its traces with no undoable step since this copy
        was taken (a refresh, an unlogged update) stays kept: nothing undoes
        that. Only ids this tree links or lists are worth keeping, and an id
        with traces now needs no keeping. The ids out_of_sight stay out: the
        redo of a rename of an object with no traces passes the ids it took
        out of sight, since no section step replays that rename, so the tree
        being replaced can still keep them from before it, and the redo
        would show the old name again.

        The other way round, an id this copy keeps that the tree being
        replaced links but no longer keeps was let go since this copy was
        taken: by a section step (a section redo of a rename, an object
        delete) that the step installing this copy did not make. The step's
        own sections have already put back what its action kept. So such an
        id stays out, unless it is one of brought_back: the undo of a rename
        of an object with no traces passes the ids that rename took out of
        sight, since no section step brings those back. An id the tree being
        replaced does not link at all is new to it (the redo of a rename
        brings back the id it kept for the new name), and stays.

            Params:
                previous (HostTree): the tree being replaced
                out_of_sight (set): kept ids the step takes out of sight
                brought_back (set): kept ids the step brings back
        """
        ids = self._ids
        linked = {oid for edge in self._edges for oid in edge} | self._members
        for oids in previous._kept.values():
            for oid in oids:
                if oid in linked and oid not in out_of_sight and not ids.isLive(oid):
                    self.keep(oid)
        # ids this copy kept that got traces since it was taken, or that the
        # tree being replaced let go
        previous_linked = (
            {oid for edge in previous._edges for oid in edge} | previous._members
        )
        for name in list(self._kept):
            still = previous._kept.get(name, ())
            self._kept[name] = {
                oid for oid in self._kept[name]
                if not ids.isLive(oid) and (
                    oid in still or oid in brought_back or oid not in previous_linked
                )
            }
            if not self._kept[name]:
                del self._kept[name]

    def _reserve(self, name : str) -> int:
        """A kept id for a name with no visible id: a name a link names
        before it has traces (a dangling host in a file, a rename target)."""
        oid = self._ids.issue(name)
        self._kept.setdefault(name, set()).add(oid)
        self._stale = True
        return oid

    # the name projection
    @property
    def objects(self) -> dict:
        """name -> {"hosts": set, "travelers": set}, for the visible links."""
        if getattr(self, "_edges", None) is not None:
            self._build()
        return self._objects

    @objects.setter
    def objects(self, value : dict):
        self._objects = value

    def _visible(self, oid : int) -> bool:
        if oid in self._hidden:
            return False
        ids = self._ids
        if ids.isLive(oid):
            return True
        name = ids.name_of.get(oid)
        return name is not None and oid in self._kept.get(name, ())

    def _visibleIds(self, name : str) -> set:
        return (self._ids.live(name) | self._kept.get(name, set())) - self._hidden

    def _fresh(self) -> bool:
        """True if the projection matches the ids and links now, and is
        exactly the visible links, so a write can update it in place."""
        return (
            not self._stale and self._exact
            and self._built == (self._ids.version, self._hidden)
        )
    def _pairOf(self, t : int, h : int):
        """The name pair of a visible link, or None."""
        if not (self._visible(t) and self._visible(h)):
            return None
        t_name, h_name = self._ids.name_of[t], self._ids.name_of[h]
        return None if t_name == h_name else (t_name, h_name)

    def _entry(self, name):
        """The projection's entry for a name, created in place. A new entry
        lands last, which is its place unless a name placed after it is
        already listed; then the projection is marked for a rebuild."""
        if name not in self._objects:
            place = self._order.get(name)
            if place is None or place < self._last_place:
                self._stale = True
            else:
                self._last_place = place
            self._objects[name] = {"hosts": set(), "travelers": set()}
        return self._objects[name]

    def _register(self, names):
        """Put names the tree does not list yet at the end of its order."""
        for name in names:
            if name not in self._order:
                self._order[name] = self._next_place
                self._next_place += 1

    def _build(self):
        """Rebuild the name projection if the ids changed since it was built,
        or a write could not update it in place."""
        key = (self._ids.version, self._hidden)
        if self._built == key and not self._stale:
            return
        self._pair_edges = {}
        names = {
            self._ids.name_of[oid] for oid in self._members if self._visible(oid)
        }
        for t, h in self._edges:
            pair = self._pairOf(t, h)
            if pair is not None:
                self._pair_edges.setdefault(pair, set()).add((t, h))
                names.update(pair)
        # a name back on screen that the order dropped (an undone delete)
        # goes last, as add() would put it
        self._register(sorted(names - self._order.keys(), key=str))
        self._objects = {
            name: {"hosts": set(), "travelers": set()}
            for name in self._order if name in names
        }
        self._last_place = max(
            (self._order[name] for name in self._objects), default=-1
        )
        exact = True
        for t_name, h_name in sorted(self._pair_edges, key=lambda p: (str(p[0]), str(p[1]))):
            # two objects under one name can link two names both ways; the
            # projection refuses the second as add() would
            if t_name in self._reachable([h_name], "hosts", False):
                exact = False
                continue
            self._objects[t_name]["hosts"].add(h_name)
            self._objects[h_name]["travelers"].add(t_name)
        # a read never shows a host that is also a host of another of the
        # object's hosts (checkRedundantHosts)
        self._trimmed = self._trim()
        self._exact = exact and not self._trimmed
        self._built = key
        self._stale = False

    def _trim(self) -> list:
        """Take each redundant host off the projection, the way
        checkRedundantHosts always has, and return the (traveler, host)
        pairs taken."""
        objects = self._objects
        removed = []
        for obj_name in list(objects):
            superhosts = self._reachable(
                list(objects[obj_name]["hosts"]), "hosts", True
            )
            for superhost in superhosts:
                if superhost in objects[obj_name]["hosts"]:
                    objects[obj_name]["hosts"].remove(superhost)
                    objects[superhost]["travelers"].remove(obj_name)
                    removed.append((obj_name, superhost))
        return removed

    def _addEdges(self, new : set):
        new = new - self._edges
        if not new:
            return
        in_place = self._fresh()
        self._edges |= new
        if not in_place:
            self._stale = True
            return
        for t, h in new:
            pair = self._pairOf(t, h)
            if pair is None:
                continue
            links = self._pair_edges.setdefault(pair, set())
            if not links:
                self._entry(pair[0])["hosts"].add(pair[1])
                self._entry(pair[1])["travelers"].add(pair[0])
            links.add((t, h))

    def _removeEdges(self, gone : set):
        gone = gone & self._edges
        if not gone:
            return
        in_place = self._fresh()
        self._edges -= gone
        if not in_place:
            self._stale = True
            return
        for t, h in gone:
            pair = self._pairOf(t, h)
            links = self._pair_edges.get(pair) if pair else None
            if not links:
                continue
            links.discard((t, h))
            if not links:
                del self._pair_edges[pair]
                self._objects[pair[0]]["hosts"].discard(pair[1])
                self._objects[pair[1]]["travelers"].discard(pair[0])

    def _addMembers(self, oids : set):
        new = oids - self._members
        if not new:
            return
        in_place = self._fresh()
        self._members |= new
        if not in_place:
            self._stale = True
            return
        for oid in new:
            if self._visible(oid):
                self._entry(self._ids.name_of[oid])

    def _writeIds(self, name : str) -> set:
        """The ids a new link of this name joins: its visible ids, or one
        kept for it if it has none."""
        oids = self._visibleIds(name)
        return oids or {self._reserve(name)}

    def _dropVisible(self, t_name : str, h_name : str):
        """Remove the visible links from t_name's objects to h_name's."""
        t_ids, h_ids = self._visibleIds(t_name), self._visibleIds(h_name)
        self._removeEdges(
            {(t, h) for t, h in self._edges if t in t_ids and h in h_ids}
        )

    # writes
    def add(self, obj_name : str, hosts : list):
        """Add an entry to the host tree.
        
            Params:
                obj_name (str): the name of the object
                hosts (list): the hosts of the above obj

            Returns:
                (list): the hosts that were refused because the edge would have
                    made obj_name a host of itself, directly or through a chain
        """

        if isinstance(hosts, str):
            hosts = [hosts]

        self._register([obj_name] + list(hosts))
        for name in [obj_name] + list(hosts):
            self._addMembers(self._writeIds(name))
        
        # An object may not end up hosting itself: the app states this to the
        # user in setHosts and in the field's host-assignment drag ("An object
        # cannot host itself", "Objects cannot host each other"), but those are
        # caller-side checks, so any path that did not repeat them could still
        # build a cycle. renameObject was such a path. The invariant is enforced
        # here instead so no caller can bypass it, and it is checked one host at
        # a time because an earlier host in the list can be what makes a later
        # one cyclic.
        refused = []
        for host in hosts:
            if host == obj_name or obj_name in self.getHosts(host, True):
                refused.append(host)
                continue
            self._addEdges({
                (t, h)
                for t in self._writeIds(obj_name)
                for h in self._writeIds(host)
            })
        
        # special case: if one of the hosts if hosted by another of the hosts, trim to lowest-level host
        self.checkRedundantHosts()

        return refused
    
    def checkRedundantHosts(self):
        """Check if any objects are hosted by multiple objects that are already hosts of each other."""
        self._build()
        trimmed = self._trim() if self._exact else list(self._trimmed)
        for t_name, h_name in trimmed:
            self._dropVisible(t_name, h_name)
    
    def removeObject(self, obj_name : str):
        """The object is gone.

        Deleting an object's last trace already made its ids invisible and
        took the ids kept for its name out of sight (ObjectIds.drop), so its
        links stay, dormant, and an undo that brings it back brings them
        back. Here the name leaves the tree's order, and for a caller that
        removes an object outright while it still has traces, the links of
        those ids are removed. The ids kept for the name are left alone: a
        redo that empties an object a step kept (a section of an import,
        redone on its own) keeps it again before the series data calls this.
        """
        if self._order.pop(obj_name, None) is not None:
            self._stale = True
        live = self._ids.live(obj_name) - self._hidden
        if not live:
            return
        self._removeEdges(
            {(t, h) for t, h in self._edges if t in live or h in live}
        )
        self._members -= live
        self._stale = True
    
    def renameObject(self, old_name : str, new_name : str, keep_old=False):
        """Rename an object in the tree.

        The object under the new name gets a copy of each visible link of the
        old one. A rename can collapse two objects into one: renaming a
        traveler to its host's name, or renaming a host and its traveler to
        the same name in one edit. The relationship between them then has
        only one end left, so it is not copied instead of becoming a
        self-host edge. Deeper collisions (the new name is a grand-host of
        the old one) are refused as add() refuses them.

            Params:
                old_name (str): the original name of the object
                new_name (str): the new name for the object
                keep_old (bool): True if the old object still exists (a rename
                    on only some of its sections). Its links are untouched
                    either way; without keep_old the old object is treated as
                    gone here, and its links go dormant once its last trace is
                    renamed.
        """
        ids = self._ids
        old_ids = self._visibleIds(old_name)
        host_copies, traveler_copies = [], []
        for t, h in self._edges:
            if not (self._visible(t) and self._visible(h)):
                continue
            t_name, h_name = ids.name_of[t], ids.name_of[h]
            if t in old_ids and h_name != new_name:
                host_copies.append((h_name, h))
            elif h in old_ids and t_name != new_name:
                traveler_copies.append((t_name, t))
        if not keep_old:
            # the old object's links stay with its ids: dormant once its last
            # trace is renamed, back if an undo brings it back. The ids kept
            # for the old name go out of sight with it.
            HostTree.renames += 1
            for oid in self._kept.get(old_name, ()):
                self._renamed[oid] = HostTree.renames
            self._release(old_name)
            self._hidden = frozenset(old_ids)
            if self._order.pop(old_name, None) is not None:
                self._stale = True
        try:
            # the object under the new name: its newest live id, else the
            # newest kept for the name, else one kept until its traces come
            live = ids.live(new_name) - self._hidden
            kept = self.keptIds(new_name) - self._hidden
            new_id = max(live) if live else (max(kept) if kept else self._reserve(new_name))
            self._register(
                [new_name] + sorted({h for h, _ in host_copies}, key=str)
                + sorted({t for t, _ in traveler_copies}, key=str)
            )
            self._addMembers({new_id})
            copies = [
                (new_name, new_id, h_name, h) for h_name, h in sorted(host_copies)
            ] + [
                (t_name, t, new_name, new_id) for t_name, t in sorted(traveler_copies)
            ]
            for t_name, t, h_name, h in copies:
                if t_name in self.getHosts(h_name, True):
                    continue
                self._addEdges({(t, h)})
            self.checkRedundantHosts()
        finally:
            self._hidden = frozenset()
    
    def clearHosts(self, obj_name : str):
        """Clear ONLY THE HOSTS for a specific object.

        Only the links on screen: a link to a host that is gone now is
        dormant, and comes back with that host.
        """
        for host in self.getHosts(obj_name):
            self._dropVisible(obj_name, host)

    def dropDormant(self):
        """Forget the links with an end that cannot come back. Called when
        the undo history is cleared: only an undo can bring back an id that
        lost its last trace. Nothing visible changes."""
        self._edges = {
            (t, h) for t, h in self._edges if self._visible(t) and self._visible(h)
        }
        self._members = {oid for oid in self._members if self._visible(oid)}
        self._renamed = {}
    
    def _reachable(self, start : list, edge : str, only_secondary : bool):
        """Collect every name reachable from start by following one edge type.

        Iterative with a visited set. The recursive version this replaces had no
        visited set, so a cycle recursed until the stack overflowed; cycles are
        now refused by add(), but a tree loaded from a file written before that
        check existed can still contain one, and traversal has to survive it to
        get far enough to repair it.

        For acyclic input the result is identical to the recursive version: every
        name reachable at distance >= 1 from the origin, or >= 2 when
        only_secondary is True. A name reachable at both distances is included
        either way, which is what checkRedundantHosts relies on.

            Params:
                start (list): the origin's direct neighbors
                edge (str): "hosts" or "travelers"
                only_secondary (bool): True to omit the direct neighbors
        """
        found = set() if only_secondary else set(start)
        seen = set(start)
        stack = list(start)
        while stack:
            name = stack.pop()
            if name not in self._objects:
                continue
            for nxt in self._objects[name][edge]:
                found.add(nxt)
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return list(found)

    def getHosts(self, obj_name : str, traverse=False, only_secondary=False):
        """Get the hosts of a certain object.
        
            Params:
                obj_name (str): the object to get the hosts of
                traverse (bool): True if returning the hosts of hosts and so on
        """
        if obj_name not in self.objects:
            return []
        
        hosts = list(self.objects[obj_name]["hosts"]).copy()
        if not traverse:
            return hosts
        return self._reachable(hosts, "hosts", only_secondary)
    
    def getTravelers(self, obj_name : str, traverse=False, only_secondary=False):
        """Get the objects that are hosted by the requested object
        
            Params:
                obj_name (str): the host of the returned objects
                traverse (bool): True if returning the travelers of travelers and so on
        """
        if obj_name not in self.objects:
            return []
        
        travelers = list(self.objects[obj_name]["travelers"]).copy()
        if not traverse:
            return travelers
        return self._reachable(travelers, "travelers", only_secondary)
    
    def getObjToUpdate(self, obj_names : list):
        """Get object names that require table updating in the GUI if the given obj(s) are modified."""
        modified_objs = set(obj_names)
        for name in obj_names:
            modified_objs = modified_objs.union(
                self.getTravelers(name, True)
            )
        return modified_objs
    
    def getDict(self):
        """Return the tree in dict format.

        Object names and their host lists are both sorted: the hosts are a set in
        memory, so unsorted output made identical content serialize to different
        bytes across processes (canonical ordering).
        """
        d = {}
        for obj_name in sorted(self.objects, key=str):
            hosts = self.objects[obj_name]["hosts"]
            if not hosts:
                continue
            d[obj_name] = sorted(hosts, key=str)
        return d

    def copy(self):
        """A copy of the links, dormant ones included, and of the ids kept
        for names without traces, on the same ids."""
        c = HostTree.__new__(HostTree)
        c.series = self.series
        c._ids = self._ids
        # in the order the saved tree lists its names, as a tree read back
        # from its saved form would have them (merge walks this order)
        order = []
        for name, hosts in self.getDict().items():
            order.append(name)
            order.extend(hosts)
        # the names a copy keeps are the linked ones, dormant links included
        linked = {oid for edge in self._edges for oid in edge}
        c._reset(
            set(self._edges), self._members & linked, order,
            kept={name: set(oids) for name, oids in self._kept.items()},
            renamed=dict(self._renamed),
        )
        return c

    def getHostGroup(self, obj_name : str, obj_pool=None):
        """Get the full list of obj names in a host group with the given obj.
        
            Params:
                obj_name (str): an object in the host group.
        """
        host_group = [obj_name]
        stack = [obj_name]
        while stack:
            n = stack.pop()
            travelers = self.getTravelers(n)
            hosts = self.getHosts(n)
            for n in (travelers + hosts):
                if n not in host_group and (not obj_pool or n in obj_pool):
                    host_group.append(n)
                    stack.append(n)
        return host_group
    
    def merge(self, other, regex_filters=None, restrict_to=[]):
        """Merge two host trees together.
        
            Params:
                other (HostTree): the other host tree
                regex_filters (list): the list of regex filters required to pass
        """
        for obj_name, d in other.objects.items():

            if restrict_to and obj_name not in restrict_to:
                    continue

            
            if (
                    obj_name not in self.series.data["objects"] or
                    not passesFilters(obj_name, regex_filters)
            ):
                continue

            hosts = d["hosts"]
            hosts = [h for h in d["hosts"] if passesFilters(h, regex_filters)]
            self.add(obj_name, hosts)
    
    def getASCII(self, obj_name : str, hosts=True, prefix="", _path=()):
        """Get an ASCII representation of the hosts/travelers of an object.
        
            Params:
                obj_name (str): the name of the object
                hosts (bool): True if host tree, False if traveler tree
                prefix (str): used in recursion
                _path (tuple): the ancestors of obj_name, used in recursion to
                    stop at a cycle. A path check rather than a visited set: a
                    name legitimately appears more than once in this output when
                    two objects share a host, and that must keep printing twice.
        """
        if prefix == "":
            tree_str = obj_name + "\n"
            if obj_name not in self.objects:
                return tree_str
        else:
            tree_str = ""
        
        path = _path + (obj_name,)
        objs = sorted(list(self.objects[obj_name][("hosts" if hosts else "travelers")]))
        for i, obj in enumerate(objs):
            # determine if extra statement should be added
            extras = sorted(list(self.objects[obj][("travelers" if hosts else "hosts")]))
            extras.remove(obj_name)
            if extras:
                s = "also hosts:" if hosts else "also hosted by:"
                extra_str = f" ({s} {', '.join(extras[:3])}{('' if len(extras) <= 3 else '...')})"
            else:
                extra_str = ""
            
            if i == len(objs) - 1:
                tree_str += prefix + "└── " + obj + extra_str + "\n"
                new_prefix = prefix + "    "
            else:
                tree_str += prefix + "├── " + obj + extra_str + "\n"
                new_prefix = prefix + "│   "
            if obj in self.objects and obj not in path:
                tree_str += self.getASCII(obj, hosts, new_prefix, path)
        
        return tree_str


def generate_directory_tree_string(path, prefix=""):
    tree_string = ""
    
    # Check if the path is a directory
    if os.path.isdir(path):
        # Get list of files and directories
        items = os.listdir(path)
        items.sort()
        for i, item in enumerate(items):
            item_path = os.path.join(path, item)
            # Determine the correct prefix for each item
            if i == len(items) - 1:
                tree_string += prefix + "└── " + item + "\n"
                new_prefix = prefix + "    "
            else:
                tree_string += prefix + "├── " + item + "\n"
                new_prefix = prefix + "│   "
            # Recurse if the item is a directory
            if os.path.isdir(item_path):
                tree_string += generate_directory_tree_string(item_path, new_prefix)
    else:
        tree_string = f"{path} is not a directory\n"
    
    return tree_string

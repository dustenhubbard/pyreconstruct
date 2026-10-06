import os

from .filters import passesFilters
from .object_ids import ObjectIds

class HostTree():
    """Which objects host which.

    A link joins two object ids (datatypes/object_ids.py), not two names, so
    it belongs to the objects that had those names when it was made. Deleting
    an object leaves its links in place but dormant: they show again if an
    undo brings that object back, and a new object that takes the old name
    does not get them.

    Callers still speak names. Reads go through a name projection of the
    links whose two ends are both visible (ObjectIds.visible), rebuilt when
    the links or the ids change. When an undo brings an old object back while
    a new one has its name, the name shows the links of both.
    """

    def __init__(self, host_dict : dict, series):
        """Create the HostTree from a dictionary of (obj_name, hosts)
        
            Params:
                host_dict (dict): the dictionary of (obj_name, hosts)
                series (Series): the series that contains the host tree
        """
        self.series = series
        ids = getattr(getattr(series, "data", None), "object_ids", None)
        # a tree with no series keeps its own ids; every name then holds a
        # reserved id, and the tree behaves as a plain name tree
        self._ids = ids if ids is not None else ObjectIds()
        # (traveler id, host id)
        self._edges : set[tuple[int, int]] = set()
        # ids registered by add() whether or not they have links, so a name
        # stays in the tree as it always has
        self._members : set[int] = set()
        # ids treated as gone while a rename runs (see renameObject)
        self._hidden : frozenset = frozenset()
        self._edges_version = 0
        self._built = None
        self._objects : dict = {}
        self._trimmed : list = []

        for obj_name, hosts in host_dict.items():
            self.add(obj_name, hosts)

    # -- the name projection ------------------------------------------------ #
    @property
    def objects(self) -> dict:
        """name -> {"hosts": set, "travelers": set}, for the visible links."""
        if getattr(self, "_edges", None) is not None:
            self._build()
        return self._objects

    @objects.setter
    def objects(self, value : dict):
        self._objects = value

    def _changed(self):
        self._edges_version += 1

    def _visible(self, oid : int) -> bool:
        return oid not in self._hidden and self._ids.visible(oid)

    def _visibleIds(self, name : str) -> set:
        return self._ids.visibleIds(name) - self._hidden

    def _build(self):
        """Rebuild the name projection if the links or the ids changed."""
        key = (self._edges_version, self._ids.version, self._hidden)
        if self._built == key:
            return
        ids = self._ids
        pairs = set()
        for t, h in self._edges:
            if self._visible(t) and self._visible(h):
                t_name, h_name = ids.name_of[t], ids.name_of[h]
                if t_name != h_name:
                    pairs.add((t_name, h_name))
        objects : dict = {}
        self._objects = objects
        for oid in self._members:
            if self._visible(oid):
                objects.setdefault(
                    ids.name_of[oid], {"hosts": set(), "travelers": set()}
                )
        for t_name, h_name in sorted(pairs, key=lambda p: (str(p[0]), str(p[1]))):
            for name in (t_name, h_name):
                if name not in objects:
                    objects[name] = {"hosts": set(), "travelers": set()}
            # two objects under one name can link two names both ways; the
            # projection refuses the second as add() would
            if t_name in self._reachable([h_name], "hosts", False):
                continue
            objects[t_name]["hosts"].add(h_name)
            objects[h_name]["travelers"].add(t_name)
        # the same trim checkRedundantHosts makes, so a read never shows a
        # host that is also a host of another of the object's hosts
        self._trimmed = []
        for obj_name in list(objects):
            superhosts = self._reachable(
                list(objects[obj_name]["hosts"]), "hosts", True
            )
            for superhost in superhosts:
                if superhost in objects[obj_name]["hosts"]:
                    objects[obj_name]["hosts"].remove(superhost)
                    objects[superhost]["travelers"].remove(obj_name)
                    self._trimmed.append((obj_name, superhost))
        self._built = key

    def _writeIds(self, name : str) -> set:
        """The ids a new link of this name joins: its visible ids, or one
        reserved for it if it has none."""
        oids = self._visibleIds(name)
        return oids or {self._ids.reserve(name)}

    def _dropVisible(self, t_name : str, h_name : str):
        """Remove the visible links from t_name's objects to h_name's."""
        t_ids, h_ids = self._visibleIds(t_name), self._visibleIds(h_name)
        gone = {(t, h) for t, h in self._edges if t in t_ids and h in h_ids}
        if gone:
            self._edges -= gone
            self._changed()

    # -- writes ------------------------------------------------------------- #
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
        
        # An object may not end up hosting itself: the app states this to the
        # user in setHosts and in the field's host-assignment drag ("An object
        # cannot host itself", "Objects cannot host each other"), but those are
        # caller-side checks, so any path that did not repeat them could still
        # build a cycle. renameObject was such a path. The invariant is enforced
        # here instead so no caller can bypass it, and it is checked one host at
        # a time because an earlier host in the list can be what makes a later
        # one cyclic.
        for name in [obj_name] + list(hosts):
            members = self._writeIds(name)
            if not members <= self._members:
                self._members |= members
                self._changed()

        refused = []
        for host in hosts:
            if host == obj_name or obj_name in self.getHosts(host, True):
                refused.append(host)
                continue
            new = {
                (t, h)
                for t in self._writeIds(obj_name)
                for h in self._writeIds(host)
            }
            if not new <= self._edges:
                self._edges |= new
                self._changed()
        
        # special case: if one of the hosts if hosted by another of the hosts, trim to lowest-level host
        self.checkRedundantHosts()

        return refused
    
    def checkRedundantHosts(self):
        """Check if any objects are hosted by multiple objects that are already hosts of each other."""
        self._build()
        for t_name, h_name in list(self._trimmed):
            self._dropVisible(t_name, h_name)
    
    def removeObject(self, obj_name : str):
        """The object is gone.

        Deleting an object's last trace already made its ids invisible, so
        its links stay, dormant, and an undo that brings it back brings them
        back. Here only a reserved id (a name with no traces) is let go, and
        the links of any id that still has traces are removed, for a caller
        that removes an object outright.
        """
        self._ids.release(obj_name)
        live = self._ids.live(obj_name) - self._hidden
        if not live:
            return
        gone = {(t, h) for t, h in self._edges if t in live or h in live}
        self._edges -= gone
        self._members -= live
        self._changed()
    
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
        self._build()
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
            # trace is renamed, back if an undo brings it back
            ids.release(old_name)
            self._hidden = frozenset(old_ids)
        try:
            new_id = ids.reserve(new_name)
            if new_id not in self._members:
                self._members.add(new_id)
                self._changed()
            copies = [
                (new_name, new_id, h_name, h) for h_name, h in sorted(host_copies)
            ] + [
                (t_name, t, new_name, new_id) for t_name, t in sorted(traveler_copies)
            ]
            for t_name, t, h_name, h in copies:
                if t_name in self.getHosts(h_name, True):
                    continue
                if (t, h) not in self._edges:
                    self._edges.add((t, h))
                    self._changed()
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
        lost its last trace."""
        ids = self._ids
        kept = {(t, h) for t, h in self._edges if ids.visible(t) and ids.visible(h)}
        members = {oid for oid in self._members if ids.visible(oid)}
        if kept != self._edges or members != self._members:
            self._edges = kept
            self._members = members
            self._changed()
    
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
        """A copy of the links, dormant ones included, on the same ids."""
        c = HostTree.__new__(HostTree)
        c.series = self.series
        c._ids = self._ids
        c._edges = set(self._edges)
        c._members = set(self._members)
        c._hidden = frozenset()
        c._edges_version = 0
        c._built = None
        c._objects = {}
        c._trimmed = []
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

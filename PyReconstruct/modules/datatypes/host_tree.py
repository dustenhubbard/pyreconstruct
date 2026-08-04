import os

from .filters import passesFilters

class HostTree():

    def __init__(self, host_dict : dict, series):
        """Create the HostTree from a dictionary of (obj_name, hosts)
        
            Params:
                host_dict (dict): the dictionary of (obj_name, hosts)
                series (Series): the series that contains the host tree
        """
        self.objects = {}

        for obj_name, hosts in host_dict.items():
            self.add(obj_name, hosts)

        self.series = series
    
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
        
        for name in ([obj_name] + list(hosts)):
            if name not in self.objects:
                self.objects[name] = {
                    "hosts": set(),
                    "travelers": set(),
                }
        
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
            self.objects[obj_name]["hosts"].add(host)
            self.objects[host]["travelers"].add(obj_name)
        
        # special case: if one of the hosts if hosted by another of the hosts, trim to lowest-level host
        self.checkRedundantHosts()

        return refused
    
    def checkRedundantHosts(self):
        """Check if any objects are hosted by multiple objects that are already hosts of each other."""
        for obj_name in self.objects:
            superhosts = self.getHosts(obj_name, True, True)
            for superhost in superhosts:
                if superhost in self.getHosts(obj_name):
                    self.objects[obj_name]["hosts"].remove(superhost)
                    self.objects[superhost]["travelers"].remove(obj_name)
    
    def removeObject(self, obj_name : str):
        """Remove an object from the tree."""
        if obj_name not in self.objects:
            return
        
        hosts = self.getHosts(obj_name)
        for host in hosts:
            self.objects[host]["travelers"].remove(obj_name)
        travelers = self.getTravelers(obj_name)
        for traveler in travelers:
            self.objects[traveler]["hosts"].remove(obj_name)
        del(self.objects[obj_name])
    
    def renameObject(self, old_name : str, new_name : str):
        """Rename an object in the tree.

        A rename can collapse two objects into one: renaming a traveler to its
        host's name, or renaming a host and its traveler to the same name in one
        edit. The relationship between them then has only one end left, so it is
        dropped instead of becoming a self-host edge. Deeper collisions (the new
        name is a grand-host of the old one) are caught by add().
        """
        hosts = [h for h in self.getHosts(old_name) if h != new_name]
        travelers = [t for t in self.getTravelers(old_name) if t != new_name]
        self.removeObject(old_name)
        self.add(new_name, hosts)
        for traveler in travelers:
            self.add(traveler, [new_name])
    
    def clearHosts(self, obj_name : str):
        """Clear ONLY THE HOSTS for a specific object."""
        # check for existence of object
        if obj_name not in self.objects:
            return
        
        hosts = self.getHosts(obj_name)
        for host in hosts:
            self.objects[host]["travelers"].remove(obj_name)
        self.objects[obj_name]["hosts"] = set()
    
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
            if name not in self.objects:
                continue
            for nxt in self.objects[name][edge]:
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
        return HostTree(self.getDict(), self.series)

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

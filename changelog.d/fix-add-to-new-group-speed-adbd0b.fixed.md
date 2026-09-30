- **Adding many objects to a new group is fast.** `Add to group...` rebuilt
  the whole menu bar once per object when the group was new, so 2,000 objects
  took about 40 seconds with nothing on screen. It now rebuilds it once and
  finishes in under a second.

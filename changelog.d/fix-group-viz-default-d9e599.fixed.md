- **`Section.setGroupVisibility` no longer raises on its own default.** The
  signature makes `group_viz` optional, but calling the method without it raised
  `AttributeError: 'NoneType' object has no attribute 'items'`. An early version
  guarded the argument first; a later rewrite moved the mapping walk ahead of the
  guard, so the first statement executed on the default was `None.items()`. No
  in-app path reached it, because the only in-tree caller is `Section.__init__`
  and it passes `series.groups_visibility`, which `Series.initGroupViz` returns
  as a dict (`{}` at worst) and never as `None`. Scripts driving `Section`
  directly did reach it, which is where an optional argument is meant to be used.
  The guard is back: omitting the argument, or passing `None` or an empty
  mapping, now means there is nothing to apply and leaves `traces_group_hide`
  untouched. The parameter's type hint said `List[str]` while the body walked it
  with `.items()`, so it now reads `Dict[str, bool]`, and the docstring names the
  default's behavior.

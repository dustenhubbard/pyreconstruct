- **Removing objects from a group no longer fails partway.** `Remove from group...`
  stopped with an error when the selection included an object that was not in the
  group, or when the group had come back through an undo. It now finishes and
  removes the emptied group from the `Groups` menu.

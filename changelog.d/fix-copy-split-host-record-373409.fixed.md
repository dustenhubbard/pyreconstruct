- **Undoing or redoing an object copy or split on one section keeps the right
  hosts.** Before, a redo there could bring the new object back without its
  host, an undo could leave an existing object with the copied host instead of
  its own, and copying an object whose host has no traces stopped with an error.

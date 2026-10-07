- **Host groups in the 3D scene follow a series undo.** After `Clear host(s)...`
  and an undo, `Select object's host group` and `Organize scene...` still used
  the hosts from before the undo. The scene kept the host tree it first saw for
  the series, and an undo or redo puts a new one in its place. The scene now
  reads the open series' host tree each time.

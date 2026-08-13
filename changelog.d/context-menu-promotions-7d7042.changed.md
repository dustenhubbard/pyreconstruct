- **Recoloring objects from the palette is easier to find, is no longer
  labeled as autoseg-only, and can now run over the whole series.** The
  context row "Reapply autoseg colors..." sat inside `Object attributes >` on
  the object list (and one menu deeper in the field), and its name undersold
  it: the palette assigns a stable color to any object name, with only
  unmodified `autoseg_<id>` names recovering their exact import color, so
  users without autoseg objects had no reason to try it. The row now reads
  "Reapply palette colors..." and sits at the top level of the object menus'
  settings section, directly below the `Object attributes >` submenu it left.
  A new `View > Recolor all objects from palette...` action applies the same
  recoloring to every object in the series as one undoable pass; locked
  objects are skipped rather than blocking the operation, and the
  confirmation dialog states how many objects will be recolored and how many
  locked ones will be skipped. The renamed row keeps its internal action
  name, so a stored keyboard shortcut still binds.

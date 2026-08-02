- **An opacity of `0` in the 3D scene is no longer discarded.** Setting an
  object fully transparent, either with the `[` shortcut or by typing `0` into
  the opacity field of the 3D scene's Edit attributes dialog, was read as "no
  opacity was chosen" rather than as the value zero. `VPlotter.modifySelected`
  applied the dialog's opacity under `if alpha:`, so a `0` never reached
  `SceneObject.setAlpha` at all, and the four `generate3D` methods in
  `PyReconstruct/modules/backend/volume/objects_3D.py` tested the saved value
  the same way, so reloading a scene holding a fully transparent object brought
  it back at the object list's opacity instead (at `1` for a ztrace). All six
  guards now test `is not None`, which is the distinction the dialog already
  draws: its float field returns `None` for a blank entry and a real number
  otherwise.

- **An island inside an object's own hole now shows in 3D.** A positive trace
  drawn inside a negative trace of the same object filled and then the hole
  cleared it, so the mesh and the volume `3D ▸ Export quantitative data`
  measures left the island out. PyReconstruct now fills it again after the
  hole, and a hole inside such an island clears again after that. Objects
  without an island mesh exactly as before.

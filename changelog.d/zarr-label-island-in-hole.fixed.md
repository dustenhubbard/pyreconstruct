- **Zarr label export keeps an island inside an object's own hole.** A
  positive trace drawn inside a negative trace of the same object was filled
  and then cleared with the hole, so the island came out as 0. PyReconstruct
  now fills it again after the hole, the same way the 3D volume does.

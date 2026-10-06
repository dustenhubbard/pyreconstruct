- **A negative trace beside an island in a hole clears the island's edge
  again.** A negative trace that touched an island inside the object's own
  hole, or sat less than a voxel from it, was not applied again after the
  island refilled, so the island kept edge voxels the negative should have
  cleared, in the 3D mesh and its measured volume. PyReconstruct now clears
  them again after the island, as it does when there is no hole around it.
  Zarr label export does the same for a negative that touches an island.

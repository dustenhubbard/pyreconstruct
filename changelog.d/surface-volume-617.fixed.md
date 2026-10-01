- **Surface-mode meshes no longer grow half a voxel past the traces.** Voxels
  on a trace's outline counted as inside, so a square 10 voxels wide filled 11
  by 11, and `Export quantitative data` reported volumes 3 to 18% high at the
  default XY resolution.

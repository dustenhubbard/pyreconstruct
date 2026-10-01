- **`From neuroglancer zarr...` opens a Zarr that has no voxel size.** It
  stopped with an error. Now it uses 4 nm pixels and 50 nm sections, and labels
  with no voxel size are read on the same grid as the images.

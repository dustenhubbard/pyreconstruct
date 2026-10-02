- **The label overlay opens a Zarr whose labels have no size.** Labels with no
  `resolution` or `voxel_size` now sit on raw's grid, as they do on import,
  instead of failing to load.

- **Zarr export keeps the exact pixel size.** The voxel size was cut to whole
  nanometers, so 2.54 nm pixels were stored as 2 nm and pixels under 1 nm as 0,
  which also made label import from those Zarrs fail.

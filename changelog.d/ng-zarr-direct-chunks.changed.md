- **Neuroglancer Zarr export writes far fewer files and uses less memory.**
  Empty areas are not stored, and the export no longer copies the Zarr after
  writing it.

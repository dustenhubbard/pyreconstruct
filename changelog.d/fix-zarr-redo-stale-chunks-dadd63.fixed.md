- **`Update image scales` removes temporary files from a stopped conversion.**
  They stayed in the zarr, and zarr counted each one as an extra chunk.

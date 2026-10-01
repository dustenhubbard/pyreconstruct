- **Neuroglancer export handles a gap in section numbers.** After a section was
  deleted, exporting a group with traces on both sides of the gap stopped with
  an error, and labels after the gap sat one slice off from their images. Labels
  now line up with the sections the Zarr holds.

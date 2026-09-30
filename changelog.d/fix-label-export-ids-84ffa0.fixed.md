- **Every object gets its own label in a Neuroglancer (Zarr) export.** Labels
  came from a hash of the name that ignored case and punctuation, so `Axon`
  and `axon` became one segment, and an object named `0` or `_` got label 0
  and was left out as background. Each object in the group now gets its own
  number starting at 1, and `gt_lookup` lists the objects from every section,
  not just one.

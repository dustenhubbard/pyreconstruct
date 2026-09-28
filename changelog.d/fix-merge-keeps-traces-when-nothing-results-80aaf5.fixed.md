- **A merge that produces no outline leaves the traces alone.** A trace smaller
  than one merge grid cell has nothing to outline, and merging it used to
  delete the inputs before finding that out. The merge now stops first and says
  to zoom in on very small traces.

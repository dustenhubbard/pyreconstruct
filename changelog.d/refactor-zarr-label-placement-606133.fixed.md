- **The Zarr label overlay now draws labels where label import puts their
  traces.** Labels offset in y from raw, or shorter than raw, were drawn away
  from their imported traces, and a gap in a Zarr's sections showed a section
  another section's slice. The overlay and import now place labels with one
  calculation.

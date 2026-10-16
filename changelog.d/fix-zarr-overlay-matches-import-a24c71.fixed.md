- **The Zarr label overlay now draws labels where label import puts their
  traces.** Labels offset in y from raw, or shorter than raw, were drawn away
  from their imported traces, and on a Zarr with a gap in its sections the
  overlay showed another section's labels. The overlay now places labels the
  way label import does.

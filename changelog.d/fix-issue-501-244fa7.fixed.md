- **Making a new series from a Zarr no longer changes that Zarr.** The import
  wrote `true_mag`, `window`, `sections` and `alignment` into the source while
  it built the series and put back only some of them, and only when it
  finished. A failed import left the source with the wrong sections and an
  identity alignment, and left the new images Zarr behind so a retry with the
  same name failed. The source is now opened read only, and a failed import
  removes the images Zarr it started.

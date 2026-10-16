- **`Series > Images > Crop scaled images around an object...` writes a copy of
  the series' scaled images that keeps only the pixels near one object, in the
  Dev build.** The dialog takes the object, a radius in microns, the source zarr
  and the output path, with the gap handling of `crop_zarr.py` as checkboxes,
  refuses the same inputs before anything is written, runs the crop behind a
  progress dialog whose `Cancel` stops it, and writes `crop_log.txt` inside the
  output naming this PyReconstruct build.

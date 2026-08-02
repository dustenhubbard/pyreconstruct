- **Every slider in `Series ▸ Options` shows its value while you drag it, in the
  units the setting is actually stored in.** The sliders were a handle on a blank
  groove with no number anywhere, so the only way to find out what a setting was
  set to was to close the dialog and watch what the program did. The **CPU usage**
  slider is the one that cost someone real time: it reads as a share of the
  machine's cores, and a setting that looked like four workers ran eight, with
  nothing on screen to check it against. It now reads `50% (5 of 10 workers)`,
  resolved through the same `determine_cpus` the image-to-zarr converter calls, so
  the worker count on the label is the worker count that will start. **Scale bar
  size** reads as a percentage of the field width and **XY Resolution** in the 3D
  section as the percentage of the way from the coarsest voxel to the finest. All
  of them carry tick marks now, so the distance the handle has traveled is
  readable at a glance, and so does the **Overlap threshold** slider in the series
  import dialog, which already showed its number.

  **Opening `Series ▸ Options` no longer shrinks the scale bar by itself.** The
  width is stored from 20 to 100 but the slider ran from 0 to 100, so the dialog
  squeezed the value on the way in and squeezed it back on the way out. The
  squeeze does not round trip: 60 of the 81 values it can hold came back one
  lower than they went in, the shipped default of 25 among them, so pressing OK
  on a dialog nobody had touched made the scale bar a point narrower, every time.
  The slider carries the 20 to 100 range itself now and the squeeze is gone, so
  what you set is what is stored. The stored range, the default and the drawn
  scale bar are unchanged.

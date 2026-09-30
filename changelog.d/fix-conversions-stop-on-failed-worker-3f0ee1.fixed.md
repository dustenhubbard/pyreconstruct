- **A Zarr conversion that fails partway now says so.** When a section failed,
  the Task Error window showed and then the conversion carried on: the export
  left a Zarr of blank images, the label import said it had worked, and a new
  series from a Zarr was still built. Now the export deletes the Zarr it made
  and exits with an error, the label import skips its success message, and no
  new series is created.

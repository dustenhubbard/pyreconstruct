- **Zooming no longer raises on a zarr whose conversion stopped partway.** A
  conversion that stops early can write a scale's chunks without its `.zarray`,
  and PyReconstruct still offered that scale. Zooming to it raised `KeyError`,
  and a section with no finished scale raised on load. PyReconstruct now offers
  only scales with a `.zarray` and draws the nearest finished one. A section
  with no finished scale opens with no image, `Optimize...` in the section list
  skips it, and `Copy view to clipboard` still works. Reading the image size no
  longer writes a `.zgroup` into an unfinished array, so running the update
  again finishes it.

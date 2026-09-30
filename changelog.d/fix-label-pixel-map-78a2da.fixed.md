- **Clicking a label in the Zarr overlay now selects the label drawn there.**
  The right half of each label pixel picked its neighbor, so `Merge labels`
  could rewrite the wrong label on disk, and panning by part of a pixel drew the
  overlay offset from the image under it.

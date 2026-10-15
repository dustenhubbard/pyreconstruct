- **PyReconstruct offers a zarr's image names when a series names its images
  another way.** When `Series > Images > Find/change image directory` or the
  images-not-found prompt points at a zarr that holds none of the series' image
  names, every section is paired with the image that carries the number in its
  image name, a few sections are shown with their traces over the proposed
  images, and on confirmation the names are applied to the open series the way
  `Edit all image sources...` does. The zarr is never changed, and the series
  file changes when you save.

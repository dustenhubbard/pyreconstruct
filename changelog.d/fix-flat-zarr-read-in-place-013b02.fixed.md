- **Opening a section of an old zarr, with each image at its root, no longer
  rearranges the zarr.** Loading a section of that layout moved every image
  into a new scale_1 folder, so opening the series changed its files on disk.
  The image is now read where it is, as its only scale, and the image size,
  SVG and PNG export, and brightness and contrast read it there too. A zarr
  with scale folders is read as before. `Update image scales` needs scale_N
  folders, so PyReconstruct no longer offers it for that layout, and the menu
  item explains why instead of starting.

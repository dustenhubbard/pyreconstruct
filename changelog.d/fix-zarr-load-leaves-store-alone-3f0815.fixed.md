- **Going to a section with no image in a zarr series no longer deletes the
  full-resolution images and moves scale_2 to scale_16 inside scale_1.** Loading
  a section checked for the first zarr layout, with each image at the root, by
  testing whether the section's image name was in the zarr. zarr reads a blank
  name as the zarr itself, and a scale's name as that scale, so a blank section
  passed the test, and the load made scale_1 again, empty, and moved every
  other scale into it. The series then could not find its images, and a
  second load of a section with no image deleted the rest. Now loading a
  section never moves anything in the zarr, and the images are read from it
  read-only.

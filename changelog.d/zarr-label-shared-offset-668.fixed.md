- **Zarr labels that share an offset with the images import over them.**
  Labels were placed by their own offset alone, so a Zarr whose images and
  labels both start away from 0 brought the labels in shifted.

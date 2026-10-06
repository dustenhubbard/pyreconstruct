- **`Convert to scaled images` is faster.** Each worker writes the scales of
  its own image to the Zarr. It used to send every scale back to one process
  that compressed and wrote all of them. With 5 workers, forty 24576 by 24576
  sections took 133 seconds before and 29 seconds after.

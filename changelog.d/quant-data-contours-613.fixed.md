- **`Export quantitative data` writes the CSV when a selected object is in
  contours mode.** A contours-mode object has no surface or volume, and it
  counted as an error, which kept the whole file from being written. It is now
  left out of the CSV, and the notice names it.

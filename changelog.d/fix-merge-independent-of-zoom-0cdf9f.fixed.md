- **Merging traces gives the same outline at any zoom.** Merge used to work on
  the screen's pixels, so a merge while zoomed in kept more detail than the
  same merge while zoomed out. It now works on a grid tied to the image, four
  cells per image pixel, and the view no longer matters.

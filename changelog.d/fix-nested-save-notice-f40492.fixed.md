- **A save started during another save shows a notice, not an error report.**
  Saving, closing or backing up while a save was still writing opened the
  error-report window, and from `File` > `Save` it opened two. Closing also shut
  the window before the save was done. Now PyReconstruct says the second save
  was skipped, and the window stays open.

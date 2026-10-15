- **Saving a series while an undo or redo across its sections is still
  running is skipped with a notice.** Opening another series at one of the
  undo's progress updates asked to save this one, and that save wrote the
  restored sections with the series data from before the undo. After a
  brightness/contrast profile rename was undone that way, the saved series
  named a profile no section had and failed to open. A series saved that way
  now opens on the default profile.

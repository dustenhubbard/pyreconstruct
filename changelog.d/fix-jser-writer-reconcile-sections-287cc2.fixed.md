- **A deleted section no longer comes back the next time the series is opened.**
  Deleting a section, saving, and reopening could put the section back, with the
  z-trace points that used to cross it still gone and a "Delete section" line
  still in the log. Nothing reported an error at any point, so the first sign was
  a section reappearing in the section list some time later, and deleting it a
  second time did the same thing again. If the section deleted was the
  highest-numbered one, every save from then on failed instead, with a crash
  report and a progress dialog that would not go away, until the series was
  closed and reopened.

  The .jser writer built its list of sections from the files it found in the
  series' hidden working directory rather than from the series' own index of
  sections, and never compared the two. `Series.deleteSections` removes both the
  file and the index entry, but the 2D field is still holding the deleted
  section, and every save writes that held section's file back out, including the
  save the delete itself performs while rebuilding the lists. The file therefore
  returned while the index entry stayed gone, and the writer believed the file.
  For the highest-numbered section the returning file's number was past the end
  of the sections array, which raised `IndexError` out of the save; only
  `OSError` was handled, so the save crashed rather than reporting a failure, and
  since nothing removed the file, the next save raised in the same place.

  The writer now reads exactly the sections the index names, so a section file
  the series no longer lists cannot reach the .jser, and `Section.save` declines
  to write a section the series has deleted, so the stale file is not created in
  the first place. That second part also matters after a crash, because the
  unsaved-work recovery scan reads the same directory and has no index to check
  it against.

- **A save that would drop a section now refuses instead, and says which
  section.** The reverse disagreement, a section the series lists whose working
  file has gone missing or become unreadable, used to write that section into the
  .jser as `null`, report the save as successful, and replace the previous .jser
  with one short a section. Because the save is atomic, delivery of the
  incomplete file was reliable and the last good copy was gone. The missing
  section cannot be recovered from the working directory in either case, so the
  .jser already on disk is the only copy of it that is left; the save now stops
  before writing anything and names the sections and the directory involved.
  Deleting every section in a series refuses on the same grounds: a .jser with no
  sections is one PyReconstruct declines to open.

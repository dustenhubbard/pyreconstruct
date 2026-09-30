- **Deleting every section is refused instead of crashing.** The section list
  used to delete all the section files, clear undo, and then crash, leaving a
  series with no sections that could not be saved. It now says a series needs
  at least one section and deletes nothing.

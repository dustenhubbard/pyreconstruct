- **Switching to a palette of another length no longer crashes.** Picking a
  shorter or longer palette in `Edit all palettes...`, or removing the current
  one, kept the old buttons and crashed. A palette CSV with no rows is now
  refused, and importing a palette marks the series as changed.

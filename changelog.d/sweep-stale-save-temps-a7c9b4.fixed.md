- **Opening a series cleans up files left behind by an interrupted save.** A
  crash or power loss in the middle of a save could leave a hidden `.save-`
  temp file next to the .jser, as large as the series itself, and nothing ever
  removed it. PyReconstruct now deletes these when a series opens. It leaves
  alone any that changed in the last ten minutes, in case a save is still
  writing one.

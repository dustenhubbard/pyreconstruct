- **De-randomize no longer stops with a project half decoded.** It checks every
  image and file before it moves one, and when something is wrong it leaves the
  project as it was and says what to fix. Deleted sections, a `.DS_Store`,
  `.TIF` images and a `decode.txt` made on Windows all decode now.

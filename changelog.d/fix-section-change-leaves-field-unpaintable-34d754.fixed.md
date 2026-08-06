- **A section change that cannot read its section file no longer leaves the field
  permanently broken.** `changeSection` moved the field onto the new section
  first and read the section and its image afterwards, so for the length of that
  read the field held no section layer at all -- the move swaps it with the B
  section's, which is empty until the first section change of a session -- and a
  read that failed left it that way for good. `paintText` reads the section layer
  on every paint event, so from that point every repaint raised `AttributeError:
  'NoneType' object has no attribute 'getTrace'`, and because a window cannot be
  asked to stop repainting, the error window reopened as fast as it was closed;
  the app had to be killed from Task Manager. Reported against 1.21.0 on Windows
  after double-clicking an object in the object list, a jump that saves every
  section immediately before reading one back, where the file can still be held.
  The section and its view are now built before anything moves, so a failure
  leaves the field on the section it was already showing and the underlying error
  is reported once, in the ordinary way.

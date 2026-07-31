- **The 2D field selects a locked object's traces again.** Clicking one did
  nothing, "Select all traces" passed it over, "Invert selection" left it out and
  "Find in field" framed it without selecting it, while the object list selected
  locked rows freely. Locking an object prevents mutations that change
  quantitative data (traces added, deleted or modified) and nothing else, so
  refusing selection was too wide, and the two invert commands answered the same
  question two different ways. `Section.addSelectedTrace` dropped the trace, and
  `findTrace` and `pointerRelease` each carried a second copy of the check around
  their own selection. Those refusals used to be the only thing standing between
  a locked object and cut, paste attributes, the arrow-key translate, the knife,
  a pointer drag and the focus-mode split; every one of those now refuses through
  a lock check of its own (`refuseLockedTraces`), so dropping the selection
  refusal gives up no protection. Hiding, unhiding, copying, zooming to and
  adding to the 3D scene work on a locked object's traces from the field as well.

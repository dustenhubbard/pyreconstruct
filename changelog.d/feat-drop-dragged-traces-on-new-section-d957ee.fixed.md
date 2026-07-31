- **Dragging traces in the field and changing section before letting go no
  longer looks like it deleted them.** A pointer drag hides the traces it is
  carrying in their section's `temp_hide` list and draws them under the cursor
  instead, and only the release that ends the gesture puts them back. The scroll
  wheel pages sections, so the button can be held while the field moves to
  another section, and nothing tied the two ends of the gesture to one section:
  the release cleared `temp_hide` on the section then on screen rather than the
  one the traces came off, and translated that section's selection, which
  `changeSection` had just emptied. The drop therefore moved nothing and said
  nothing, and the traces stayed hidden on the section they came from. A
  temp-hidden trace is also left out of `traces_in_view`, which is what hit
  testing reads, so on paging back they were invisible and unclickable until that
  section was reloaded. Nothing was ever lost on disk, because `temp_hide` is not
  saved. The drag now ends when the field changes under it, the traces reappear
  where they started, and the field says so instead of going quiet.

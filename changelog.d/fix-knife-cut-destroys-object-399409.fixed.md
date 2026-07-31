- **The knife no longer deletes the object when the cut cannot be made.**
  `cutTrace` deleted the selected traces and only then recreated one trace per
  returned piece, so a cut that returned nothing left the object gone, put
  nothing in its place, showed no message and reported success. Two paths reach
  that state: `cut_closed_traces` dropped any trace whose outline crosses itself,
  which freehand tracing produces routinely, and a "% original trace" threshold
  high enough to discard every piece threw away the cut's own output. Both are
  now decided before anything is committed. A trace that crosses itself is
  refused with a message naming the reason, a cut that comes back empty is
  refused outright, and a knife click with no drag behind it leaves the section
  untouched rather than deleting and recreating the selection.

- **A second mouse button part way through a cut no longer abandons it.** A
  drawing tablet's barrel button, or any stray press while the pen was down, fell
  through `mousePressEvent`'s "favor right click" branch, which clears the stroke
  drawn so far and drops the left-click state the knife commits on, and then
  opened the field context menu over the object being cut. The stroke was lost
  and a menu nobody asked for stood under a still-moving pen, one release away
  from "Delete selected". A cut in progress now owns the gesture and the press is
  ignored, the way a line trace in progress already suppresses that menu. Clear
  **Ignore the other mouse buttons** in the knife's right-click dialog, or in
  `Series ▸ Options... ▸ Knife`, to get the older behavior back.

- **Dragging with the pointer no longer crashes when the press was dropped.** A
  finger touch on Windows, or a touch gesture, could swallow the press but leave
  the left button marked as down, and the next move raised an error. A pointer
  move now does nothing unless the pointer tool saw the press.

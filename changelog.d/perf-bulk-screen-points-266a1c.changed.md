- **Zoomed out on a dense section, the field redraws faster.** The points of
  every trace in view are now mapped to the screen in one pass and handed to
  the drawing code in one buffer, instead of one point object at a time. Each
  trace is still drawn on its own and in the same order, so what you see does
  not change.

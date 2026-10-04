- **Negative traces in a transformed Reconstruct contour import in the right
  order.** When a contour in a Reconstruct XML section carried its own
  transform, PyReconstruct dropped the point reversal it applies to negative
  traces, so those traces came in wound the other way. They now come in the
  same order with or without the transform.

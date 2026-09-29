- **Small traces far from the origin now get the right area, centroid, and
  radius.** PyReconstruct measures each trace from its own first point, so a
  tiny trace at large coordinates reads the same as it would anywhere else, and
  other traces change only in the last digits.

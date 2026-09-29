- **Small traces far from the origin now get the right area, centroid, and
  radius.** PyReconstruct measures each trace from its own first point instead
  of from the section origin, so a tiny trace at large coordinates or under a
  large alignment shift reads the same as it would anywhere else. Other traces
  may change in the last digits.

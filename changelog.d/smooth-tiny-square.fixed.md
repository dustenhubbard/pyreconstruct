- **Smoothing a very small trace no longer turns it into a triangle.** A closed
  trace a few thousandths of a unit across could come back from smoothing as
  three points, a thin triangle in place of the drawn shape. PyReconstruct now
  leaves it as it was. Larger traces smooth exactly as before.

- **Export to XML keeps negative traces negative.** Reconstruct reads a closed
  trace as negative when its points run clockwise, and the export reversed
  every negative trace without checking which way it ran. A hole imported from
  XML, or any trace drawn clockwise, came back with the opposite sign. The
  points now go out in the direction that matches the trace.

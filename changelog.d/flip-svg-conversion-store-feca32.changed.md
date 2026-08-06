- **SVG and PNG section export now read traces from the section's columnar
  store instead of the object model — the first consumer flipped, and the
  output is byte-identical.** `export_svg` walks the store's
  insertion-order contour enumerator through `ContourView`/`TraceView`
  instead of `Section.contours`, so the exported paths keep exactly the
  order, membership and geometry they had before; the export was hashed
  before and after on every section of a real series, including one whose
  contour insertion order and sorted order disagree, and every byte matched.
  A regression test now pins the export's content and paint order against
  the object model on a section built to make a wrong enumeration visible.

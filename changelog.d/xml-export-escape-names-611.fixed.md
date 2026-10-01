- **Export to XML handles `&` and `"` in image and palette names.** An image
  file such as `A&B.tif`, or a palette trace with `&` or `"` in its name,
  stopped the export with `XMLSyntaxError`. Those names now export and import
  back unchanged.

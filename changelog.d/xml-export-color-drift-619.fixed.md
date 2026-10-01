- **Palette and z-trace colors survive an XML round trip.** The `.ser` keeps
  these colors to three decimals, and many of them read back one step darker,
  so a color like `(76,20,200)` drifted lower on every export and import. Each
  channel now goes out as a value that reads back the same.

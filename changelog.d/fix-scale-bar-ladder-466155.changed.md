- **The scale bar width setting moves the scale bar.** The bar is drawn at the
  longest round length that fits the width you set, and the list of lengths it
  was allowed to pick from held four values per decade: 1, 2.5, 5 and 10. The
  width setting holds 81 values. Sweeping all 81 through a real render of the
  widget, at six zoom levels from a dense view out to a whole section, only
  three or four of them drew a different bar, and as many as 51 positions in a
  row drew the same bar to the pixel. The list now carries every whole number
  from 1 to 10 plus 1.5 and 2.5, which puts 8 to 10 different bars in the same
  sweep, and every length it can print is still a number you would put in a
  figure: 3 µm, 40 µm, 250 µm. Tick marks divide each length by a count picked
  for that length rather than always by five, so a 20 µm bar reads 5, 10, 15
  instead of 4, 8, 12, 16.

  **A length prints one way now.** The same 10 µm bar printed `10 µm` or
  `10.0 µm` depending on which side of a decade the zoom happened to be on,
  because the arithmetic behind it returned a whole number in one case and a
  decimal in the other and the label was whatever that came out as. Tick labels
  carried a trailing `.0` on every value. Both go through one formatter now,
  which drops trailing zeros and does nothing else.

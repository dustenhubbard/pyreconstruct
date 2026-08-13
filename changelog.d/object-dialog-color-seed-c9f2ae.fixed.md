- **Fixed the object attributes dialog opening with a gray color swatch (and
  a white picker) for objects that have a color.** The dialog was never given
  the selection's color, only its name and tags. The swatch now shows the
  selection's color, checked across every section the objects appear on:
  when all their traces agree it shows solid, and when any trace anywhere
  disagrees it shows a diagonal split, the predominant color against a blank
  half, so the discrepancy is visible while the attributes are being edited.
  The shown color is display only: confirming the dialog without using the
  picker leaves every trace's color exactly as it was, so an object whose
  colors vary cannot be accidentally repainted to the one color the swatch
  happened to show.

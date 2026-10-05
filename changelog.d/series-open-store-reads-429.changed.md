- **Opening a series is faster.** The pass that measures every trace when a
  series opens now reads each section's points from the array the section
  already keeps, instead of building a list of points per trace and converting
  it back. On my 37,000-trace autoseg series that pass went from about 2.1 to
  1.8 seconds.

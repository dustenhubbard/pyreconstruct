- **The main window now opens at 70% of the screen rather than 50%, and
  `View > Reset window` puts it back there at any time.** The first-launch
  fallback, which is also what a restore falls back to when the saved geometry
  no longer fits the connected displays, took 50% of the primary screen in each
  direction: a quarter of the screen by area, which read as small. It now takes
  70% in each direction, about half the screen by area, still centered rather
  than near-maximized. On a 1280x720 screen that is 896x504 at (192, 108).

  `View > Reset window` applies that same centered default immediately, and
  overwrites the saved geometry so the reset survives a restart. It reads
  nothing from the window's current position or size, which is the point: a
  window parked off every screen or shrunk too small to grab had no recovery
  short of quitting and clearing `window/geometry` by hand.

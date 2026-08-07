- **A small confetti burst when you copy an error report.** Clicking **Copy
  report to clipboard** in the error window now throws a dozen small coloured
  dots out of the button for about half a second, fading them out before they
  reach the edge of the window, alongside the "Copied ✓" label it already
  showed. It fires only on a copy that actually reached the clipboard, so it is
  feedback and not decoration: where the clipboard is unavailable the label
  still changes and nothing is thrown. The
  particles are ordinary child widgets of the error window, animated with Qt's
  own property animations and deleted when they land, so repeating the click
  leaves nothing behind. The log viewer's own copy button is deliberately
  untouched.

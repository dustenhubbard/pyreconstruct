- **The What's new dialog has a "Don't show again" button, and the Help menu
  has a matching "Show what's new after updates" toggle to switch the popup
  back on.** The button closes the dialog and stops the startup popup for
  good, including across later updates. It suppresses only the unasked popup:
  Help > What's new stays an explicit request and always opens. The two
  controls read and write one stored preference, next to the dialog's
  once-per-version record, so they can never disagree, and the toggle rereads
  it every time the Help menu opens. While the popup is off the last-seen
  version is deliberately not advanced, so switching it back on picks the
  ordinary rules up intact: a release missed while it was off shows on the
  next launch, and a release already seen stays seen.

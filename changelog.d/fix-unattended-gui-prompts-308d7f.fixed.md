- **A scripted GUI session can now open a series whose images are missing
  without hanging on a dialog nobody is there to click, by setting
  `PYRECON_UNATTENDED=1`.** `user_is_present()` decides whether the startup
  prompts in `MainWindow.openSeries` are raised at all, and it was answering
  "can anyone see and answer a modal?" by checking whether Qt was drawing
  offscreen. That is only a proxy. A click-test harness, a screenshot script or
  a computer-use agent launches on a real platform with a real `QApplication`,
  so the proxy said a user was present and the prompt was raised into a window
  nothing would ever click: opening a series whose `src_dir` does not resolve
  stalled indefinitely on "Images Not Found", with the non-cancelable series
  code dialog and the unscaled-zarr question behind it. Nothing Qt can observe
  tells such a session apart from a real user's, so the caller now says so
  itself, and every prompt behind that predicate takes the same deliberate
  no-user answer it already takes offscreen. Unset, which is every ordinary
  launch, nothing changes: an interactive user opening a series with no images
  is still offered the chance to locate them.

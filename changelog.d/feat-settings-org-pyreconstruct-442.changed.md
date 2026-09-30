- **Settings are now stored under PyReconstruct instead of KHLab.** Your
  preferences, shortcuts, and per-series settings move to a folder or registry
  key named after the app, such as `~/.config/PyReconstruct` on Linux,
  `com.pyreconstruct.PyReconstruct.plist` on macOS, and
  `HKEY_CURRENT_USER\Software\PyReconstruct` on Windows. The first launch copies
  your existing values across, and each series copies its own the first time you
  open it. The old KHLab settings are left in place, so an older version still
  finds them.

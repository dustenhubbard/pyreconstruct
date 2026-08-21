- **Keyboard shortcuts now appear in the right-click menus on macOS.** Qt hides
  shortcut text in context menus when the platform asks it to, and macOS asks by
  default. So Ctrl+H showed beside "Hide selected traces" in the menubar and
  nothing beside the same row in the field menu, which is the surface where that
  row is actually used. Every menu row the app builds now opts in, so the keys
  read the same on Windows, Linux and macOS.

- **Linux AppImage Dev users: re-run the Dev install once to keep getting
  nightlies.** An AppImage Dev install from before this change only looks for
  the older date-only nightly tags, so run `curl -fsSL https://pyreconstruct.org/install.sh | bash -s -- --dev`
  again. macOS, Windows and the Linux tarball are not affected.

- **Closing PyReconstruct in its first seconds, or restarting it, no longer
  leaves the What's new popup and the launch update check pending.** Both ran
  on timers that belonged to no window, so they still fired on the window that
  had closed. The main window now owns both timers and stops them when it
  closes.

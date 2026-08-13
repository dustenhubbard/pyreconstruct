- **The "trace crosses itself" knife refusal now says what to try and where
  to find it.** The old dialog told the user a selected trace crosses itself
  and cannot be cut, and stopped there; users hitting it on automatically
  segmented traces had no idea the app ships a clean-up tool for the stray
  traces that segmentation leaves behind. The message
  now explains that the outline crosses over itself so the cut cannot tell
  inside from outside, confirms nothing was changed, and points at
  Series > Clean up to remove the stray traces automatic segmentation
  leaves behind, a common cause of the refusal. A test reads
  the menu path off the live menus, so renaming them fails the suite instead
  of leaving the message pointing at a menu that no longer exists.

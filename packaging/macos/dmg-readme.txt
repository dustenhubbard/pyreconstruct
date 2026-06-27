How to open PyReconstruct (first launch)
========================================

PyReconstruct is not yet code-signed by Apple (this is a preview build), so the
first time you open it macOS will block it with a message like:

    "PyReconstruct" cannot be opened because Apple cannot check it for
    malicious software.

This is expected for an unsigned app. To allow it to run:

  1. Drag PyReconstruct onto the Applications folder (the alias in this window).

  2. Open Terminal (Applications > Utilities > Terminal), paste this line, and
     press Return:

         xattr -dr com.apple.quarantine /Applications/PyReconstruct.app

     (No output means it worked.)

  3. Open PyReconstruct from Applications or Launchpad as usual.

You only need to do this once per install.

------------------------------------------------------------------------------
Prefer not to use Terminal?
  Double-click PyReconstruct (it will be blocked), then open
  System Settings > Privacy & Security, scroll down, and click "Open Anyway".
  Confirm, then open PyReconstruct again.
------------------------------------------------------------------------------

This step goes away once PyReconstruct is code-signed and notarized.

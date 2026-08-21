# PyInstaller runtime hook, bundled ONLY into the Dev flavor (see the spec's
# FLAVOR handling). Runs before any application import, so everything that
# reads PYRECON_APP_NAME -- the pinned update channel, the settings store,
# the series ownership marker, the window title -- sees the Dev identity.
# setdefault, not assignment: an explicit override in the environment wins.
import os

os.environ.setdefault("PYRECON_APP_NAME", "PyReconstruct Dev")

"""Whether the new macOS look is shown: only on a macOS Dev build launched
with PYRECON_MAC_UI=1.

The look is held until it is ready (2026-10-21): the system fonts and accent
ring (gui/utils/fonts.py), System, Light and Dark (gui/utils/appearance.py)
and the line icons on the mouse palette (gui/palette/line_icons.py). The code
stays, so it can be tested on a Mac Dev build by launching with the switch
set; with it unset that build draws what it drew before. The native menu bar
is not part of it. Read at call time, so a test can set the switch without
reimporting.
"""
import os
import sys

from PyReconstruct.modules.constants import build_flavor

## Shows the macOS look ("1") or hides it (any other value, or unset)
ENV_SWITCH = "PYRECON_MAC_UI"


def mac_ui_enabled() -> bool:
    """True on macOS, in a Dev build, when PYRECON_MAC_UI is "1"."""
    return (
        sys.platform == "darwin"
        and build_flavor.is_dev_build()
        and os.environ.get(ENV_SWITCH) == "1"
    )

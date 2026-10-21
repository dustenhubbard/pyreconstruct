"""Whether ROI mode is shown: off in every build unless PYRECON_ROI_MODE=1.

ROI mode is held until it is ready (2026-10-21). The code stays, so it can be
tested in any build by launching with the switch set; with it unset there is
no palette tool, no View menu item, no shortcuts row and no B key for it.
Read at call time, so a test can set the switch without reimporting.
"""
import os

## Shows ROI mode ("1") or hides it (any other value, or unset)
ENV_SWITCH = "PYRECON_ROI_MODE"

## The settings keys of its two actions, left in the defaults so a stored
## binding is kept while the feature is hidden
ACTION_KEYS = ("roibox_act", "useroi_act")


def roi_mode_enabled() -> bool:
    """True when PYRECON_ROI_MODE is "1"."""
    return os.environ.get(ENV_SWITCH) == "1"

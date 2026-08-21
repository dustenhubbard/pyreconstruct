"""Who has this series open: the identity half of the in-use guard.

The guard itself has existed for a long time: while a series is open, the
field widget drops a heartbeat file (a bare unix-timestamp filename) into the
series' hidden working directory and refreshes it every five seconds
(``FieldWidget.markTime``); ``MainWindow.openSeries`` refuses to open a series
whose heartbeat is fresher than seven seconds. What the guard could not say is
WHO has it open -- and with the stable and Dev builds installable side by side,
"another window" stops being a useful answer.

This module adds the identity: a small JSON file written next to the
heartbeat. It never gates anything by itself -- the heartbeat stays the
mechanism, because a stale owner file (a crash, a kill -9) must not lock
anyone out, and the heartbeat already expires on its own.

The file is cleaned up with everything else in the hidden dir: both
``Series.close`` and the stale-dir sweeps in ``openSeries`` remove the
directory's files wholesale.
"""

import getpass
import json
import os
import socket

OWNER_FILENAME = ".owner.json"

#: What this build calls itself in the "series in use" message. The Dev build's
#: packaging sets PYRECON_APP_NAME=PyReconstruct Dev, so a stable user who hits
#: the guard is told which of the two apps to look at.
def app_display_name():
    return os.environ.get("PYRECON_APP_NAME", "PyReconstruct")


def write_owner(wdir):
    """Record this process as the series' holder. Failure is not an error:
    identity is a courtesy on top of the heartbeat, never a gate."""
    try:
        with open(os.path.join(wdir, OWNER_FILENAME), "w") as f:
            json.dump(
                {
                    "app": app_display_name(),
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "user": getpass.getuser(),
                },
                f,
            )
    except OSError:
        pass


def read_owner(wdir):
    """The recorded holder, or None when there is none (or it is unreadable)."""
    try:
        with open(os.path.join(wdir, OWNER_FILENAME)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def describe_owner(owner):
    """One line for the "series in use" message.

    Falls back to the old wording's meaning when identity is missing, so the
    message never regresses below what it always said.
    """
    if not owner or not owner.get("app"):
        return "another window"
    app = owner["app"]
    host = owner.get("host") or ""
    if host and host != socket.gethostname():
        return f"{app} on {host}"
    return app

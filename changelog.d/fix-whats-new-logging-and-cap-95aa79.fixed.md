- **A "What's new" dialog that fails to reach you now says so in the log
  instead of leaving no trace at all.** `MainWindow.showWhatsNewStartup` wrapped
  the whole startup showing in a bare `except Exception: pass`. The intent is
  right -- a first-launch convenience must never disrupt a launch -- but a
  silent swallow meant a failure could only ever be noticed as an absence, with
  nothing anywhere to say which step declined. The handler still swallows
  everything; it now writes the exception and its traceback to the log first.

  It also records the outcome when nothing failed, distinguishing "dialog
  shown" from "not due for this version". An exception-only line cannot tell a
  showing that never happened from a gate that correctly said no, and that is
  the state a real launch left behind: no dialog, no traceback, and no way to
  tell the two apart. Help ▸ What's new logs its own failures the same way. The
  lines go to the log Help ▸ View log file already opens.

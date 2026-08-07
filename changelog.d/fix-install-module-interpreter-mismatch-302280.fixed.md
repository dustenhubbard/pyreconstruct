- **Accepting the "install the packages this feature needs" prompt no longer
  crashes the app when pip installs into a different Python than the one
  running.** The install shelled out to a bare `pip` on `PATH` and then imported
  the module in-process to report where it landed. Those are not necessarily the
  same interpreter: with a system Python beside a virtual environment, or conda
  beside homebrew, `pip` can report success having installed somewhere this
  process cannot import from, and the in-process import then raised an uncaught
  `ModuleNotFoundError`. The packaged app is built windowed, with no console, so
  there was nothing on screen to act on. The install now runs as
  `sys.executable -m pip install <name>`, targeting the interpreter that is
  about to do the import, and an import that fails anyway is reported as a
  failed install together with the exact command that would install into the
  right environment. A `pip` that is missing altogether is unaffected: that
  already reported a failed install and still does.

- **The packaged app now explains that optional packages cannot be added to it,
  instead of offering an install that cannot work.** A packaged build carries
  its own private Python and no `pip`, so neither the in-app install nor a
  `pip install` in a terminal can reach it -- the terminal's `pip` belongs to a
  different Python. `sys.executable -m pip` is not a repair there either: in a
  packaged build `sys.executable` is the application launcher rather than an
  interpreter, and it takes `-m pip install <name>` as ordinary arguments, so
  the "install" launches a second copy of PyReconstruct and the first one waits,
  invisibly, until that copy is closed. The prompt is now a plain explanation
  pointing at the from-source setup, which is how a missing system library is
  already handled.

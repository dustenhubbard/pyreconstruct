- **The command line takes a jser path positionally: `pyreconstruct
  series.jser`.** The entry point only understood `-f series.jser`, so the Linux
  installer had to write a launcher that rewrote a single non-flag argument into
  `-f` before handing it on. That shim stays for the launchers already on disk,
  but the entry point now understands both forms itself, which is what a shell
  user types and what a desktop entry's `%f` produces. Naming the same file both
  ways is accepted; naming two different files is refused rather than resolved
  silently to one of them.

- **A jser path that does not exist is reported instead of ignored.**
  `MainWindow` opens the welcome series for a filename that is not on disk, so a
  mistyped path produced a launched app, no series, and nothing said about why.
  The check now runs on the command line, before Qt starts, and exits non-zero.

- **The in-app offer to install an optional package no longer answers a
  uv-managed source install with advice that cannot work.** Declining a feature
  because `svgwrite`, `cairosvg` or `cloud-volume` is missing puts up a yes/no
  prompt, and accepting it runs `pip install <name>`. The project's documented
  from-source setup is `uv sync` (see the README), and uv does not put pip
  inside the environment it creates -- it installs packages itself and has no
  use for one. So on the setup the README tells people to use, that command
  fails before it starts: `/bin/sh: pip: command not found`. The user then saw
  the generic failure notice, whose entire content was "Something went wrong.
  Please try pip installing X in a terminal" -- naming the one command that had
  just been established not to exist, and sending them to look for a fault in
  their network or their permissions instead.

  A failed install now distinguishes "there is no pip here" from "pip ran and
  pip failed". The first gets a notice naming commands that work: `uv add
  <name>` and `uv pip install <name>` in a uv-created environment, and
  `ensurepip` followed by `pip install <name>` in any other pip-less
  interpreter, which is also told which interpreter it is. Both name the
  package's *install* name rather than its import name, so the lines can be
  copied as printed -- `cloudvolume` installs as `cloud-volume`. Ordinary
  install failures are untouched and keep the generic notice, which is honest
  advice for them.

  Every printed command targets the environment the notice is about. The
  non-uv branch spells its two lines `"<the interpreter>" -m ensurepip
  --upgrade` and `"<the interpreter>" -m pip install <name>`, quoted for paths
  with spaces, rather than bare `python` and `pip`: those resolve off PATH, and
  this branch fires precisely because PATH has no pip for the interpreter just
  named, so a bare token would add pip to -- and install the package into -- a
  different environment. The uv branch likewise says which of its two routes
  lasts: `uv add` records the package in `pyproject.toml` and `uv.lock` and
  survives later syncs, whereas `uv pip install` does not record it, so the
  next `uv sync` removes it again. That consequence was previously left to be
  inferred from "without recording it", and the README tells people to run `uv
  sync`.

  The environment is identified by the `uv = <version>` key uv stamps into
  `pyvenv.cfg`, which neither `venv` nor `virtualenv` writes, rather than by
  looking for a directory called `.venv`: a uv environment is not always named
  that, and a directory with that name was not necessarily made by uv. Whether
  a pip exists is established by looking for one rather than by matching the
  subprocess output, because the two spellings of the failure share no text --
  a shell `pip install` exits 127 with "command not found" and
  `sys.executable -m pip` exits 1 with "No module named pip".

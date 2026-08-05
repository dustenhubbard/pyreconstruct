- **SVG and PNG section export no longer ask you to install their own
  dependencies.** `File > Export > SVG` and `File > Export > PNG` reach
  `modules/backend/exports/svg_conversion.py`, which imports `svgwrite` and
  `cairosvg` -- neither of which was ever declared in `pyproject.toml`,
  `requirements.txt` or `uv.lock`. Both imports are function-local, so the
  package, the module and `Section` all imported cleanly and the gap surfaced
  only at the moment of export. It was not a crash: each menu handler is
  fronted by a `modules_available(...)` guard that has been there since the
  export was written, so what a user actually got was a dialog offering to
  `pip install` the two packages over the network, and no export until they
  accepted. Both packages are now declared and locked, so they arrive with the
  install and the prompt is gone.

  The guard itself is widened here too, because declaring `cairosvg` is what
  made its blind spot reachable. `cairosvg` does not bundle Cairo -- it
  `dlopen`s the native library at import time -- so `import cairosvg` raises
  `OSError`, not `ModuleNotFoundError`, on a machine with the wheel and no
  system Cairo. The guard caught only `ModuleNotFoundError`, and once every
  install carries the wheel that `OSError` would have escaped it as a crash
  report. It now catches both and reports them differently: a missing *package*
  still offers the pip install that fixes it, a missing *native library* names
  the system remedy instead and does not offer an install that cannot help.

  The same failure had a second way in, which is closed here as well. If you
  accept the install offer and the `pip install` succeeds, the guard imports
  the package once more to report where it landed -- and on a machine with no
  system Cairo that import raises the same `OSError`, which used to escape as
  a crash report. It is now caught, reported with the system remedy rather
  than as a success, and the install is treated as unsuccessful, so the
  feature declines cleanly instead of running on and failing at the export.
  You are not offered the install a second time, since you have just run it.

  For PNG, therefore, declaring the package is necessary but not sufficient:
  the machine also needs `libcairo2` (Debian/Ubuntu), `brew install cairo` plus
  `DYLD_FALLBACK_LIBRARY_PATH` (macOS), or a Cairo DLL on `PATH` (Windows).
  Native Cairo is still not bundled into the frozen macOS/Windows installers
  (`packaging/PyReconstruct.spec` and `build-installers.yml` install none), so
  PNG export from a shipped installer needs Cairo present on the machine -- a
  separate gap, unchanged by this release either way. SVG export has no native
  requirement and works anywhere the Python dependencies are installed.
  `docs/DEV_UV.md` records the per-platform requirement and CI installs
  `libcairo2` so the PNG assertion runs on the gate.

  `tests/test_export_svg_png.py` exports a real fixture section and checks the
  output is an SVG carrying that section's embedded image and named trace
  paths, and a PNG whose IHDR dimensions match the requested scale;
  `tests/test_modules_available_native_library.py` covers the widened guard.

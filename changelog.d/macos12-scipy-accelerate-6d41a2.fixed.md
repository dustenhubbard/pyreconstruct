- **Fixed a crash on macOS 12 the first time a trace was smoothed.** The Mac
  builds picked a scipy build that needs the newer Accelerate math library,
  which only exists on macOS 13.3 and up, so on an older Mac the app started
  normally and then died with "Symbol not found: _dstevr$NEWLAPACK" as soon as
  anything called smoothing. The builds now pick the scipy that runs on macOS
  12, and the build fails if that ever regresses. The README states the
  minimum supported systems.

- **The Beta update channel now offers a stable release when it is the newest one.**
  The Beta channel only ever looked at pre-releases, so once v1.21.0 shipped as a
  stable build and the superseded 1.21.0 betas were retired, a Beta-channel user was
  offered nothing at all: `pick_release` returned `None`, `check_for_update` reported
  `status="unknown"` with no asset, and the app showed neither an update prompt nor an
  error. Testers were silently cut off from the release everyone else had, and the
  only way out was to know, unprompted, to switch channels. The channel now offers
  whichever of the newest pre-release and the newest stable release is actually newer,
  so Beta means earlier access rather than a separate lane. The retired rolling
  developer build is still never offered on Beta, which is what the previous behavior
  was protecting.

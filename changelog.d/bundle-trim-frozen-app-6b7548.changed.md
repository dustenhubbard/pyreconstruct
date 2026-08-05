- **The macOS and Windows installers are about 13 MB smaller to download and 18 MB
  smaller once installed, with no change to what the app can do.** The PyInstaller
  spec force-bundled every submodule of scipy (972) and scikit-image (410), the
  ~7.5 MB of sample photographs scikit-image ships for its own documentation, both
  packages' test suites, and a second loose copy of the cloud-volume, numcodecs and
  zarr Python sources on top of the copies already inside the executable's archive.
  None of that is reachable from the application. The spec now names the
  subpackages the app actually reaches -- derived by running every scipy and
  scikit-image call site in a real interpreter and reading back the modules that
  loaded, so the packages' internal cross-imports are included rather than guessed
  -- and excludes the test suites, which were the only thing in the whole
  dependency graph pulling in `scipy.io`. Measured on an arm64 macOS build: the
  downloaded `.dmg` goes from 300.2 MiB to 287.2 MiB and the installed `.app` from
  821.7 MiB to 803.4 MiB.

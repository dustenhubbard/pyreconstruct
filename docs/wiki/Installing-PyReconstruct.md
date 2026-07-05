# Installing PyReconstruct

There are two ways to install PyReconstruct: a one-click installer (recommended
for most users) or a from-source install with `pip` (for developers and other
platforms).

### One-click installers (Windows, macOS, and Linux)

Download the latest build from
**[Releases](https://github.com/dustenhubbard/PyReconstruct/releases)** — no
Python required.

- **Windows** — `PyReconstruct-<version>-Windows-x86_64-Setup.exe`. This is a
  per-user installer (no administrator rights required). Builds are unsigned for
  now, so Windows SmartScreen may warn that the publisher is unknown; choose
  **More info ▸ Run anyway**. Re-running a newer installer upgrades the existing
  installation in place.
- **macOS (Apple Silicon or Intel)** — `PyReconstruct-<version>-macOS-arm64.dmg` on
  Apple Silicon, or `PyReconstruct-<version>-macOS-x86_64.dmg` on an Intel Mac. Open
  the `.dmg` and drag **PyReconstruct** onto the **Applications** shortcut. Builds are
  unsigned for now, so the first launch of a browser-downloaded copy is blocked by
  Gatekeeper. Clear the quarantine flag once in Terminal:

  ```
  xattr -dr com.apple.quarantine /Applications/PyReconstruct.app
  ```

  Alternatively, the first time macOS shows the "could not verify" dialog, open
  **System Settings ▸ Privacy & Security** and click **Open Anyway**.

> 📸 *Screenshot: the macOS `.dmg` window showing the app and the Applications drop target.*

Both macOS builds are native (arm64 and x86_64), and the in-app updater serves each
Mac its matching architecture.

- **Linux** — `PyReconstruct-<version>-Linux-installer.tar.gz`. Extract it and run
  `bash install.sh` — a no-root `.sh` installer that builds an isolated virtual
  environment, puts a `pyreconstruct` launcher on your PATH, and adds an
  application-menu entry. It needs a system **Python 3.11** (`python3.11` + `venv`;
  on Debian/Ubuntu, `sudo apt install python3.11 python3.11-venv`) and targets
  x86_64. To update, re-run `install.sh`.

### From source (Linux, other platforms, and developers)

In a Python 3.11 environment (the project pins `>=3.11,<3.12`):

```
pip install git+https://github.com/dustenhubbard/PyReconstruct
PyReconstruct
```

`pip` pulls in the runtime dependencies (PySide6, VTK, vedo, NumPy, SciPy,
scikit-image, shapely, trimesh, zarr, and others). For a full development setup
(conda environment, tests, code layout), see
[CONTRIBUTING.md](https://github.com/dustenhubbard/PyReconstruct/blob/main/CONTRIBUTING.md).

### Launching the app

- From an installer: launch **PyReconstruct** like any other installed application.
- From a source install: run `PyReconstruct` on the command line.

The command accepts a few optional flags, e.g. `PyReconstruct -f path/to/series.jser`
to open a series directly on launch. (Run `PyReconstruct --help` for the full
list.)

---
[Home](Home) · [Keeping PyReconstruct Up to Date](Keeping-PyReconstruct-Up-to-Date) ›

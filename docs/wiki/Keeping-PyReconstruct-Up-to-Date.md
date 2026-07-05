# Keeping PyReconstruct Up to Date

The frozen Windows and macOS one-click builds can update themselves from within the
app. The updater downloads the new build from GitHub Releases and **verifies it
against a published SHA-256 checksum before installing** — if the checksum can't be
reached or doesn't match, nothing is installed. (The Linux `.sh` installer updates
by re-running `install.sh` — see [Installing PyReconstruct](Installing-PyReconstruct).)

### Update channels

PyReconstruct offers two update channels, selected under **Series ▸ Options…**
(`Shift+O`) in the **Updates** section:

- **Release (recommended)** — stable builds, tagged `vX.Y.Z`.
- **Pre-release (experimental)** — the latest pre-release build (release candidates,
  tagged like `vX.Y.ZrcN`); newer features, less testing.

The default channel is **Release**.

> 📸 *Screenshot: Series ▸ Options ▸ Updates, showing the Release / Pre-release radio buttons and the "Check for updates on startup" checkbox.*

### Checking for updates

Choose **Help ▸ Check for updates…**. On an installed build, PyReconstruct checks
GitHub Releases on your selected channel (off the main thread, so the UI stays
responsive). If a newer build is found, an update dialog opens showing the new
version, the download size, and the release notes, with a **Download & Install**
button. The download is verified, then applied when you close the app, and
PyReconstruct restarts on the new version.

If you are already current, you'll see a brief "You're already up to date"
message; if no installer exists for your platform on that channel, it tells you so.

> 📸 *Screenshot: the "PyReconstruct — Update" dialog with release notes and the Download & Install button.*

### Checking automatically on startup

Under **Series ▸ Options ▸ Updates** you can enable **Check for updates on
startup**. It is **off by default**. When enabled, an installed build does a quiet
background check at most **once per day**; if an upgrade is available it shows a
status-bar notice and asks whether you'd like to view it.

### Source / `pip` installs

For a from-source install, **Help ▸ Check for updates…** instead reinstalls
PyReconstruct from a chosen Git branch with `pip` and then restarts. The branch is
configured under **Series ▸ Options ▸ Updates** (the **Branch:** field, default
`main`). The channel/installer machinery above applies only to packaged builds.

---
‹ [Installing PyReconstruct](Installing-PyReconstruct) · [Home](Home) · [Core Concepts](Core-Concepts) ›

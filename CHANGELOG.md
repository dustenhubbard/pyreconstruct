# Changelog

All notable changes to this distribution of PyReconstruct are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/).

Builds come on two channels: **Release** (stable, tagged `vX.Y.Z`) and
**Pre-release (experimental)** (release candidates, tagged `vX.Y.ZrcN`). Entries
under [Unreleased] have landed on `main` but are not yet tagged; they reach the
Pre-release channel once cut as a release-candidate tag, ahead of the next
stable release.

## [Unreleased]

## [1.21.0rc3] — 2026-07-06

### Added
- **Isolate objects and traces.** New actions to focus on a subset while
  proofreading. "Hide Other Objects" hides every non-selected object across the
  whole series so the isolation persists as you change sections (locked objects
  are hidden too, since a lock guards edits and quantification, not visibility);
  "Show all objects" restores them; and "Hide all objects" hides everything so
  objects can be revealed a few at a time. All are undoable series-wide. "Invert
  selection" flips the object-list selection, and a matching field action flips
  the trace selection on the current section. Object actions live in the object
  list's new Selection menu, its right-click menu, and the field Object submenu;
  the trace actions live in the field Traces menu. Menu-only for now. (#51)
- **Colorblind-safe colors for imported auto-segmentations.** Traces imported
  from automatic segmentation are colored from a curated, grayscale-visible,
  colorblind-distinguishable palette, deterministically mapped from each label
  id. The live label overlay uses the same mapping, so the preview matches the
  imported traces, and the color seed is exposed as an option. (#50)

### Fixed
- **3D scene now tracks 2D edits.** An already-open 3D scene updates when the
  underlying 2D traces change, instead of showing a stale mesh until the object
  is removed and re-added. (#49)
- **Copy to sections hardening.** Copying to a large or partial section range, or
  with non-decimal input, no longer hangs, and invert/empty-set edge cases are
  guarded, so copies land correctly regardless of input. (#46)
- **Correlation-alignment propagation respects locks and undo.** Propagating an
  alignment by correlation across a range now skips alignment-locked sections and
  records a single undo state, and composes the corrAlign transform in the
  correct order. (#47)

## [1.21.0rc2] — 2026-07-05

### Added
- **Copy traces to multiple sections at once.** A new "Copy to sections..."
  action places the selected trace(s) onto multiple chosen sections at the same
  field (x, y) location in one step. It sits at the top level of the field
  context menu, next to Copy (not in the Trace submenu), and is also available in
  the trace list. A picker accepts section numbers and ranges (e.g. `10-20` or
  `5, 8, 11`); each trace is re-projected through every target section's own
  transform so it lands at the identical field position regardless of that
  section's alignment, and attributes (name, color, closed, tags) are preserved.
  Traces are copied onto every chosen section, including alignment-locked ones —
  a section lock guards its transform/alignment, not its trace content. The
  source section is never modified.
- **Propagate an alignment by correlation across a range.** Align by correlation
  (`Ctrl+\`) now records its shift through the same path a manual transform uses,
  so with propagation active the correlation shift is replayed across a chosen
  section range (or as you scroll), exactly like a manual translate. With no
  propagation active, it still aligns only the current section.
- **"What's new" on demand.** A new Help ▸ What's new action reopens the
  release-notes dialog at any time, showing the recent release history (the
  running version plus the few before it). The once-per-version startup popup
  and its stored last-seen record are unchanged. (#36)
- **User-guide wiki.** The full user guide is now a GitHub wiki with a page per
  topic, surfaced from the README and reachable in-app from Help ▸ Online
  resources ▸ PyReconstruct user guide. (#34)
- **"What's new" on first launch.** On the first launch of a new version — a
  fresh install or after an update — PyReconstruct shows a dismissible "What's
  new" dialog with that version's release notes, read from the bundled
  `CHANGELOG.md` (offline-safe) with a link to the full notes on GitHub. It
  appears once per version and is modeless, so it never blocks startup.
- **Intel macOS installer.** CI now builds a native x86_64 `.dmg`
  (`PyReconstruct-<version>-macOS-x86_64.dmg`) on a `macos-15-intel` runner
  alongside the Apple Silicon arm64 build, so Intel Macs get a native installer.
  The arch-named assets are unambiguous and the in-app updater already serves
  each Mac its matching arch.
- A `pytest` test suite covering geometry/transform equivalence and the updater's
  selection, version-comparison, and checksum logic, plus a headless performance
  harness. (#2, #3)
- Reproducible fork-vs-upstream benchmarks under `benchmarks/`, with raw results,
  aggregated medians, and an equivalence report. (#1)

### Changed
- **Large-series performance.** Rewrote the per-trace geometry build and the
  affine point mapping that dominate opening and refreshing a series, with no
  change to the `.jser` format or data model. Open and refresh are **3–4× faster**
  across real autoseg series from 6 MB to 1.4 GB (up to ~4.2×); the geometry is
  verified equivalent to the previous implementation — section/object/trace counts
  match exactly and summed area/length/radius are identical on seven of the eight
  benchmark series (the largest differs by ~1e-11 relative on summed radius, from
  floating-point summation order). The work
  vectorizes `traceGeometry` into a single NumPy pass, defers the Feret-diameter
  convex hull until it is read, maps trace points straight to NumPy arrays, and
  uses [orjson](https://github.com/ijl/orjson) on the JSON load/save paths (with a
  stdlib fallback). Series-wide object operations are scoped to the sections that
  actually contain the targeted objects. (#1)
- **In-app updater polish.** The update check now runs off the GUI thread; a new
  update dialog shows the version, channel, download size, and release notes, then
  downloads and checksum-verifies the installer inline with a progress bar. Added
  an opt-in background check on startup (frozen builds, gated to once per 24 h),
  off by default. (#3)
- **Headless-capable data model (internal, behavior-preserving).** The internal
  `Series` no longer imports anything from the Qt/GUI layer. Its option storage,
  progress reporting, and user notifications now go through small injectable seams
  (`SettingsStore`, `ProgressReporter`, `Notifier`), each with a Qt-backed default
  adapter and a pure-Python one for headless use and tests. GUI callers get
  identical settings, progress, and notification behavior. (#30, #31, #33, #35)
- **In-app links point at this fork.** The Help ▸ Report issues links, the
  "PyReconstruct source code" menu link, and the user-guide link now open this
  fork's repository and wiki instead of the upstream SynapseWeb repo and the lab
  wiki. Upstream provenance and credit in the README, About dialog, and
  CONTRIBUTING are unchanged. (#34)
- **README header.** The README now leads with the social-preview card. (#29)
- **De-staled docs.** The README, user guide, and contributing guide were updated
  to reflect current reality (the Linux installer, the shipped Intel build, the
  Pre-release channel, and silent username resolution).
- Documented the Align-by-correlation propagation workflow in the user guide and
  wiki. (#39)
- Renamed the updater channels to **Release** and **Pre-release (experimental)**.

### Fixed
- **Shell-free converter launches.** The Zarr and Neuroglancer converters are now
  launched with an argument list on every platform instead of a shell command
  string. Paths read verbatim from the opened series file are passed as single
  literal arguments, so shell metacharacters in them can no longer be executed on
  a normal menu click (remote-code-execution hardening).
- **Atomic saves.** The series (`.jser`) and per-section files are now written to
  a same-directory temporary file and atomically replaced (`os.replace`), so a
  crash or a full disk mid-write can no longer truncate the only complete copy. A
  failed write surfaces an error and the series is never marked saved.
- **Clean recovery from an interrupted open.** An open that is canceled or errors
  part-way removes its partial hidden directory instead of leaving one that could
  later be offered as unsaved work and saved over the intact `.jser`. Corrupt or
  foreign files now raise a readable error rather than a raw exception.
- **Align by correlation under rotation or scale.** The correlation shift is now
  composed after the section transform, matching a manual translate, so it no
  longer drifts when the current transform is not a pure translation.
- **Edits on the flickered-away section are saved.** Saving now also writes the
  b-section held by flicker, which was previously excluded from the save and then
  discarded on close.
- **Safer, more reliable batch exports.** The Zarr/labels export threading path
  renders off-thread without touching GUI-only objects, reports worker errors
  instead of reporting an incomplete export as success, and can no longer be
  mutated from a reentered event loop mid-run.
- **Hardened self-update.** The updater cancels cleanly mid-download, refuses (in
  frozen builds) to install a download with no published checksum, targets this
  fork, and requires https for the installer/checksum URLs and every redirect.
- **Undo works on a read-only series.** The undo baseline falls back to memory
  when the hidden directory is not writable (e.g. the bundled welcome series in a
  read-only install location) instead of raising on startup.
- **Lifecycle fixes.** Undo/redo now clears the stale selected-flags list, and a
  per-series timer left over from a previously opened series is stopped, so
  background bookkeeping runs once rather than once per series opened.
- The crash-dialog bug-report link now points at this fork.
- **No username prompt on launch.** Startup no longer opens a blocking "Enter
  your username" dialog that stole focus and ignored a previously saved name.
  The username is now resolved silently: a name saved on this machine is reused,
  otherwise the OS login is used and saved. "Change username..." in the menu
  still sets it explicitly.
- Declared the `orjson` dependency in `pyproject.toml`. It powers the jser
  load/save speedups but was previously only in `requirements.txt`, so a
  pyproject-based install silently dropped it and lost both the speedup and the
  orjson code path. (#2)
- Corrected user-facing typos, blank/placeholder dialog titles, and repository
  URL casing.
- Updated the macOS dmg first-launch (Gatekeeper) instructions to match current
  macOS wording.

## [1.20.0] - 2026-06-26

### Added
- **One-click installers** built in CI: Windows (`.exe`, Inno Setup) and macOS
  Apple Silicon (`.dmg`), released from this repository via GitHub Actions
  (unsigned for now).
- **In-app updater** that downloads and installs releases from GitHub Releases,
  with a channel toggle and bundled CA certificates for TLS verification in the
  frozen app.

### Changed
- Modernized the 3D stack to **vtk 9.4.2** + **vedo 2025.5.4**, enabling native
  Apple Silicon support.
- Migrated packaging from `setup.py` to **`pyproject.toml` + setuptools-scm**
  (tag-derived versioning); `requirements.txt` is retained as an export.

### Fixed
- Frozen-build hardening: windowed-stdio, Qt, SSL, and software-OpenGL runtime
  hooks; a Mesa software-OpenGL fallback on Windows for RDP/VM sessions; and a
  frozen-Windows multiprocessing fix so the Zarr conversion runs.

[Unreleased]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.21.0rc2...HEAD
[1.21.0rc2]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.20.0...v1.21.0rc2
[1.20.0]: https://github.com/dustenhubbard/PyReconstruct/releases/tag/v1.20.0

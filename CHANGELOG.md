# Changelog

All notable changes to this distribution of PyReconstruct are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/).

Builds come on two channels: **Stable** (final releases, tagged `vX.Y.Z`) and
**Beta** (curated pre-releases, tagged e.g. `vX.Y.Z-beta-N` / `vX.Y.ZrcN`).
Entries under [Unreleased] have landed on `main` but are not yet tagged; they
reach the Beta channel once cut as a pre-release tag, ahead of the next stable
release. To run unreleased `main` before it is tagged, use a source install (see
the README's *From source (developers)* section).

## [Unreleased]

### Added
- **A keyboard shortcut for "Copy to sections...".** The action now has a
  user-configurable default of `Ctrl+Alt+C`, listed in the shortcuts dialog next
  to Copy. `Ctrl+Shift+C` was the natural sibling of `Ctrl+C` and was requested
  in review, but it is already **Toggle curation in object lists** and is
  documented as such, so the copy-to-sections key keeps the "C for copy" mnemonic
  on the otherwise unused `Ctrl+Alt` tier rather than displacing a live binding.
  The key is bound through the field only; the trace list leaves it unbound, as
  every other list menu does. A new test additionally asserts that no two actions
  in the configurable shortcut set share a default key — Qt answers such a clash
  by firing *neither* action, which is invisible until a user reports a dead
  shortcut.

### Changed
- **The "Copy to sections" picker suggests real sections from the open series.**
  The dialog's hint and input placeholder were a fixed `10-20` / `5, 8, 11`, which
  meant nothing in a series that does not run to 20. They now show the series' own
  range plus three sections sampled from it, and the hint text is shorter. Samples
  are drawn from the sections that actually exist, so a series with gaps is never
  offered an example that the picker would then reject.

### Fixed
- **Undoing an alignment change no longer leaves the alignment it removed in the
  right-click menu.** The field's "Series alignment" submenu is built once from
  the series' alignment names, and a series-wide undo or redo reloaded the field
  and the lists without rebuilding it. After undoing an "Edit alignments..."
  change that created an alignment, the submenu still offered the created name.
  Selecting it set the series to an alignment the sections no longer carry, and
  the resulting `KeyError` came from `Section.tform` inside `paintEvent`, so the
  window repainted and raised it again without end. The series-wide undo now
  rebuilds the context menus, and only when the set of alignment names actually
  changed.

## [1.21.0] — 2026-08-04

### Added
- **File ▸ Open recent series ▸ Clear recents.** The recently opened list could
  only be emptied by editing settings; it now has a menu item, separated from the
  remembered paths so it cannot be hit by a mis-click aimed at the last series.
  Clearing rebuilds the menubar so the submenu is visibly empty at once. The list
  is a computer-wide setting rather than series data, so clearing it is not
  undoable and does not mark the series modified.
- **A menubar inventory test** (`tests/test_menubar_labels.py`). The right-click
  menus have been guarded by an explicit action inventory since the frequency-first
  redesign; the menubar had no such guard. The complete tree of `main/menubar.py`
  — 113 actions and 32 submenus, separators included — is now frozen by
  `attr_name`, and the File and Series menus are additionally frozen label for
  label, so a future pass has to name anything it drops, moves or renames.
- **Data clean-up menu.** A "Clean up" submenu under the Series menu groups three
  series-wide maintenance operations, each a single undoable action with a
  progress bar over the existing `enumerateSections`/`SeriesStates` path: *Remove
  duplicate traces* (same object name and geometrically coincident on the same
  section, exact points or IoU above a threshold, default 0.95; never merges
  distinct objects), *Remove pixel-dust traces* (small closed traces at or below a
  user-chosen threshold, presented in a reviewable `PixelDustDialog` before
  anything is deleted), and *Remove empty traces* (degenerate geometry only — no
  points, zero-area closed, zero-length open — after a count-stating
  confirmation). Locked objects are left untouched. `MalformedContoursDialog` is
  generalized with an overridable column/heading spec so the review dialog reuses
  its selection/navigation/delete/export behaviour. (#88)
- **The pixel-dust threshold is expressed in pixels (px²)** rather than physical
  area, matching the "smaller than N pixels on its own image" mental model.
  `findPixelDustTraces` derives the physical cutoff per section from that
  section's magnification (`threshold_px * section.mag**2`), so one threshold
  adapts across sections of differing scale; each candidate carries both its pixel
  and physical area, the review dialog shows both columns, and the input defaults
  to 10 px². (#89)
- **Approved-colors editor for autoseg import.** The "Autoseg import colors" group
  in Series ▸ Options ▸ View hosts an `AutosegColorsWidget` beside the color seed:
  the palette renders as clickable swatches (each opening `QColorDialog`), with
  Add / Remove / "Reset to default" managing the list (floor of 2 colors, since
  the seed and Shuffle need ≥2 to reshuffle). Persists to the existing
  `autoseg_color_palette` option at computer-wide scope, storing `[]` while
  unchanged from the CVD-safe `DEFAULT_AUTOSEG_PALETTE` so users keep tracking the
  curated palette. The live preview, Shuffle and import all read that one option.
  (#82)
- **Shuffle control for autoseg import colors.** A "Shuffle colors" button and
  one-line caption on the zarr import overlay beside "Import Contours".
  `next_shuffle_seed()` rejects a candidate reproducing the current mapping, so a
  click always visibly changes the arrangement; the result is still a plain
  deterministic integer, so preview-equals-import and cross-section color
  stability are unchanged. The Series ▸ Options seed field is relabelled with a
  caption pointing at the button. Shuffling affects only the live preview and
  future imports. (#80)
- **"Reapply autoseg colors..."** on the object-list / object context menu pushes
  the *current* palette and seed onto selected objects, for objects imported
  before the color features baked their colors in. Adds
  `AUTOSEG_TRACE_PREFIX`, `label_id_from_name` and `palette_color_for_name` to
  `palette.py` (reproducing the exact import color for a parseable name, falling
  back to a `PYTHONHASHSEED`-independent `zlib.crc32` of the name);
  `series.reapplyAutosegColors` resolves per-object color once and rewrites
  through the normal per-section `editTraceAttributes` path over only the sections
  the objects appear on — one undoable operation, no per-object full-series scans.
  Goes through the `object_function` wrapper, so locked objects are blocked as for
  any bulk attribute edit, behind a confirm dialog. (#83)
- **"Copy to sections" reports the actual sections written.** The result message
  lists the section numbers that received the trace(s) rather than a count of
  those requested, collapsing contiguous runs to ranges ("2-5, 10") with
  singular/plural grammar, so a silently-skipped target is visible. Message
  building moves into a pure `format_copy_result` helper. (#87)
- **Menu parity actions and hoists.** "Invert selection" added to the trace,
  z-trace, section and flag list context menus via a shared
  `DataTable.invertSelection` that inverts only displayed/filtered rows (an active
  filter can never select a hidden row); "Copy row text" added to the object,
  trace and z-trace lists; the flag list's "Resolve" submenu hoisted to top-level
  "Mark resolved" / "Mark unresolved"; and a single dynamic "Edit ...
  attributes..." item at the top of the field context menu whose label and enabled
  state follow the selection through a pure `edit_selected_label()` helper driven
  by `checkActions`. (#77)
- **Zarr-label right-click actions restored.** "Import labels" and "Merge labels"
  and their handlers were commented out during the 2024 neuroglancer-importer
  handoff, not because they broke; every callee (`labelsToObjects`,
  `zarr_layer.mergeLabels`, `removeZarrLayer`, the overlay `selected_ids`) still
  resolves. Restoring also repairs the `ZarrPalette` "Import Contours" button and
  the `checkActions` label block, both of which referenced the missing
  handler/actions. `mergeLabels` now disables correctly at ≤1 selected label.
  (#77)
- **`docs/JSER_FORMAT.md`**: a normative description of the current `.jser`
  on-disk format — byte invariants, the hidden unpack directory, the top level and
  the holes in the sections array, the log's pseudo-CSV rules, every positional row
  documented index by index, the options bag and settings scoping, and the
  migration branches in `updateJSON`. Roughly 120 machine-checked `file:line`
  anchors, and a minimal example extracted from the doc itself that opens
  headless, deep-equals after save and round-trips byte-identically. Also lists
  the reader/writer divergences found while documenting. (#94)
- **`benchmarks/` measurement harness (Phase 0).** Replaces the withdrawn RAM
  figures and assumed hotspots with measurements. Cold and warm are explicit
  labelled conditions and never pooled; the harness observes which path
  `openJser` took and aborts on a mislabelled rep; loud manifest with hard-fail on
  missing files, uniform warmup, rotated checkout order, page cache pinned; guards
  verified by negative test. Corrected numbers (3 reps, medians): warm-vs-warm
  2.05× / 2.39× / 2.55× at 162k/324k/485k traces; cold-vs-cold 1.44-1.48×, of
  which roughly 20% of the cold spike is fork-attributable and 80% the shared
  JSON-parse/unpack path. Reading all 636 section files is 0.30 s (0.6%), so the
  file choreography is not I/O; JSON decode 15.7%, object construction 30.7%,
  geometry 53.0%, bounding a format change at about 28%. Ran on the largest
  available real autoseg series (407 MB, 161,767 traces) plus section-replicated
  derivatives, labelled synthetic — the original lab series were unavailable.
  (#96)
- **`uv.lock` is committed** (134 packages, resolved for Python 3.11, including
  `orjson==3.11.8`) and `uv sync` / `uv run` become the canonical developer setup
  in the README, `docs/USER_GUIDE.md`, `CONTRIBUTING.md` and `docs/DEV_UV.md`, with
  the plain-venv path demoted to an alternative and conda a parallel option.
  `uv lock --upgrade` is documented as the maintainer dep-bump flow. (#86)

- **3D scene auto-refresh toggle.** The `WindowActivate`-triggered stale-mesh
  regeneration is now gated behind a per-computer `3D_auto_refresh` option
  (default on), exposed both as a Scene-menu checkbox in the 3D window and in
  Series ▸ Options ▸ 3D. Manual refresh (Ctrl+R) is unchanged; re-enabling
  immediately refreshes accrued edits. (#64)
- **Developer update channel.** Third channel tracking the rolling build
  republished on every push to `main` (fixed tag `prerelease`). `pick_release`
  selects it by tag; freshness rides the monotonic setuptools-scm `.devN` in
  asset versions, so the reused tag can neither miss updates nor re-offer the
  installed build. (#66)

- **Copyable error reports.** The uncaught-error dialog now shows a full report
  (version, OS, Python, traceback) with a "Copy report to clipboard" button. The
  packaged app has no console, so lay users could not otherwise retrieve the
  traceback. (#58)
- **Handled errors are copyable too.** Handled failures (e.g. a save error via
  `_surfaceSaveError`) now route through the same copyable dialog via a
  `Notifier.notify_error` seam, instead of a plain message with no detail. Adds
  Help ▸ Report issues ▸ Copy diagnostic report for an on-demand version/OS
  report. (#60)
- **Log file and viewer.** stdout/stderr and the exception-hook report are teed
  to a per-user log file (size-bounded, one rotated backup). Help ▸ View log file
  (copyable, with Open log folder) and Help ▸ Open log folder surface it,
  restoring the console visibility lost when moving from the CLI launcher to the
  packaged app. (#61)

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
- **Six File/Series menu labels now name what they act on**, all user-reported as
  "a verb with no object". Renames only: no item moved, none was removed, and no
  keyboard shortcut changed (keys resolve through `series.getOption(act_name)` and
  every `attr_name` is untouched).
  - `File ▸ Reload` → **Restart PyReconstruct**. It saves, reloads every
    `PyReconstruct.modules` module and recreates the main window with the same
    series — it restarts the application, it does not reload the series. The
    shortcuts dialog already called it "Restart"; `Ctrl+R` is unchanged.
  - `File ▸ Open` → **Open series...** (it opens a `.jser`; `Ctrl+O` unchanged).
  - `File ▸ Open recent` → **Open recent series**.
  - `File ▸ Close` → **Close series**. It returns to the welcome series and stays
    in the app, which "Close" beside "Quit" did not convey.
  - `File ▸ New` → **New series**. All four rows create a series, so the submenu
    names the thing once rather than repeating it four times.
  - `Series ▸ Update curation from history` → **Restore object curation status
    from log**. It reads the series log (including entries offloaded to
    `existing_log.csv`), finds each object's most recent
    "Mark as curated" / "Mark as needs curation" entry and writes that status back
    onto objects whose stored status is missing or is still "needs curation". It
    never clears a status and never downgrades an already-curated object, so it
    recovers curation that the stored attributes have lost rather than
    recomputing it.
- **A second menu-label pass names the remaining File/Series objects, and
  File ▸ Projects becomes a catch-all.** Same rules as the pass above: renames
  only, nothing moved or removed, no keyboard shortcut changed, every label
  verified against its handler.
  - `File ▸ Export` → **Export series**. Both rows act on the open series:
    "To legacy Reconstruct (XML)..." converts it to a legacy `.ser`, and
    "To Neuroglancer (Zarr)..." writes its images over a chosen section range
    (plus any chosen object groups as labels) to a Neuroglancer-compatible
    zarr.
  - `Series ▸ Import` → **Import series data**, and its `From series...` →
    **From another series...** (the handler's own docstring: "Import from
    another series"). Both rows bring data into the open series — traces,
    z-traces, flags, attributes, alignments, palettes and
    brightness/contrast profiles from another `.jser`, or neuroglancer zarr
    labels converted to objects.
  - `File ▸ Projects` → **Utilities** — the maintainer's catch-all for the
    rarely used functions this submenu collects, and a signal for where
    future niche items go. Inside it, `Randomize images...` →
    **Randomize project...**, so the pair shares its noun with
    `De-randomize project...`: `randomize_project` acts on a project
    directory (codes its images and emits a single coded `.jser`) and
    `derandomize_project` reverses exactly that.
  - Housekeeping made visible by the menubar inventory test: the Alignments
    import submenu's internal `attr_name` is now `importalignmentsmenu` (it
    shared `importmenu` with Series ▸ Import, so the second `setattr`
    overwrote the first; nothing read it). Menubar `attr_name`s are now
    asserted unique.
- **Brightness and contrast are exempt from the section lock.** The lock exists
  to protect *alignment*, not image display, and that is what it actually
  gates: every `align_locked` check in the field widget is a transform
  operation (`changeTform`, `translateTform`, `affineAlign`, `corrAlign`,
  `quickAlign`, `propagateTo`, and propagate-on-section-change). The section
  table, however, refused `setBC` / `matchBC` / `optimizeBC` on a locked
  section, which made the lock mean "read-only section" — something it already
  was not, since the same lock permits copying traces onto a locked section
  (`test_copy_traces_to_sections.py`: *"a lock protects the transform, not
  trace content"*) and the field's own `setBrightness` / `setContrast`
  shortcuts have never checked it. The two paths therefore disagreed about the
  same edit and the table was the anomaly; its three lock checks are removed,
  with the reasoning recorded on `setBC`. Deliberately narrow:
  `editThickness`, `editSrc`, `modifyAllSrc` and `reorderSections` keep their
  lock checks, no transform path is touched, and two guard tests assert the
  exemption did not widen to thickness or to the transform. (#113)

- **Right-click menus are reorganized frequency-first: the everyday actions are
  now one click, not two.** All seven right-click surfaces (2D field, zarr label,
  and the object / trace / z-trace / section / flag lists) follow one shape:
  the action(s) you almost always came for at the top with their shortcuts on
  display, everyday groups next, named submenus for the long tail, table
  utilities second-from-bottom, destructive last. Specifically: the field menu's
  top strip is the four shortcut-bearing trace actions (Edit / Merge / Merge
  attributes only / Hide), hoisted out of `Trace >`; the object menu's
  `Visibility >` submenu is dissolved to a flat top-level group and
  `Comment...`, `Duplicate object`, `Add to 3D scene` and `Group >` are hoisted
  to top level; every list menu now leads with a domain action instead of
  `Invert selection`, which moves to the shared bottom utility slot beside
  `Copy <entity> values`. **No action was removed, renamed, or unbound** — all
  112 inventoried actions remain reachable and every keyboard shortcut keeps its
  key (shortcuts are keyed to internal action names, which are unchanged). The
  only label change is `Add to scene` → `Add to 3D scene`, which needs the noun
  now that it sits at top level rather than inside `3D >`.
- **The object menu's "Remove all tags" is filed honestly.** Tags are
  trace-level, so on an object menu this action strips tags from every trace of
  the selected objects, series-wide — a bulk trace operation, not an object
  attribute and not geometry (its old home). It now sits in its own group above
  `Delete objects`.
- **The trace list gains `Find > Find in field`**, mirroring what double-clicking
  a row already does, for discoverability.
- **Saved `.jser` files are minified again, so saves are faster and files are
  smaller.** The structural pretty-printing introduced in #102 was kept on the
  assumption it was nearly free. Measured, it was not: on a 391 MB series it cost
  **+11% of save time** and **about 27% more transient memory in the save path**
  (an extra ~411 MB, about one additional copy of the document), for +0.65% of
  file size. Whole-process peak memory was unchanged, which is why the cost went
  unnoticed. Minified is now the default, reversing that part of #102 —
  `saveJser` on the same 391 MB series goes **7.064 s → 6.333 s (−10.3%)** and
  **393,372,829 → 390,846,078 bytes (−0.64%)**, with save-path transient memory
  **1,922 MB → 1,511 MB (−21%)**. Smaller series shrink proportionally more
  (−3.4% on the 560 KB fixture, −2.1% on a 4.7 MB hand-traced series).
- **Canonical ordering is unchanged and still always applied.** It is the half of
  #102 that earns its place: it costs **0 bytes** and no measurable time, and it
  is what makes two saves of the same series byte-identical across processes.
  There is deliberately no way to turn it off.
- **If you were relying on the readable format, opt back in** by setting
  `PYRECON_JSER_PRETTY=1`; otherwise files that had become line-structured will
  revert to a single line on the next save. The pretty form is unchanged and
  still worth it for reading a diff — a one-trace edit on a 781 MB series is 669
  bytes of `diff` output pretty versus the whole file twice minified. The variable
  is now read on **every** write instead of once at start-up, so it can be
  changed in a running session. It replaces `PYRECON_JSER_MINIFY`, which is gone;
  the behaviour that variable selected is now the default. Both forms are the
  same JSON document and the reader accepts either, so this is
  backward-compatible in both directions.
- **Menu labels normalized** across the context menus, menubar, list menus and
  the shortcuts dialog: sentence-case intrusions fixed, Unicode `…` → ASCII
  `...` with `...` added to nine dialog-opening actions and removed from two that
  open none, a terminology verb table applied (Edit / Set values / Duplicate /
  Clear status / Delete `<thing>`), and scope stated in the label where two
  actions collided ("(this section)" vs "(entire series)"). No `attr_name`,
  option key or handler changed. (#75)
- **Object menu restructured and View toggles made checkable.** The "Operations"
  grab-bag is dissolved into "Visibility" and "Geometry" with every action
  preserved; Lock/Unlock gets a single home in Attributes and the duplicate pair
  is removed; "Export meshes" → "Export mesh as"; and the duplicate "Set
  columns..." is removed from the object-list List menu. The five "Toggle X" View
  items (Focus mode, Hide trace layer, Show all traces (ignore hidden), Hide
  image, Section blend) become checkable items named for their state, keeping
  their user-configurable shortcuts via a new `(series, "checkbox")` kbd form in
  `newAction`; checked state resyncs from live field state in `checkActions`, and
  since `setChecked` emits `toggled` while handlers are on `triggered`, the
  resync never re-fires a handler. (#76)
- **List copy actions renamed** from "Copy row text" to "Copy `<entity>` values"
  across the object, trace, z-trace, section and flag lists — the copy is
  tab-separated cell values with no header line. The object-menu submenu title
  reverts to "Object attributes" to differentiate it from trace attributes.
  Labels only; `attr_names`, shortcuts, handlers and copy behaviour unchanged.
  (#78, #79)
- **"Check series histories" now defaults to on** in the import dialog. With it
  off, the import resurrects deleted objects and duplicates renamed ones; with it
  on, deletions and renames propagate and disagreements are flagged. Since #101
  closed the loss paths that made the on-position unsafe, on is now the correct
  default on both axes. Visible consequence: conflicts that were previously
  resolved silently are now flagged, including new `import-removed_<object>`
  flags. Two tests specifically guard that a merge where both logs and the traces
  agree still produces no new flags. (#101)
- **Performance: anchor-point detection vectorized and QPoint construction
  batched.** `isAnchorPoint` becomes a lazily built, per-`Grid` cached anchor mask
  via `cv2.filter2D`, and `getAnchorTrace` a mask lookup plus boolean index; the
  scalar `isAnchorPoint` is retained byte-for-byte as the test oracle, since it
  raises `IndexError` past the last row/col where a mask lookup would silently
  answer. Exact array equality over 96 randomized grids, 60 `getExterior` runs and
  30 far-edge trials, zero mismatches. Lasso sweep on `shapes2` **13.67 s → 1.00 s
  (13.7×)**; `getAnchorTrace` alone 60-90×. Separately, per-point QPoint
  conversion is replaced by `list(starmap(QPoint, pix_pts.tolist()))` — PySide6
  exposes no bulk QPolygon constructor — which is pixel-identical by construction
  and confirmed by golden buffers over 11 shapes × 5 draw modes with 0 differing
  pixels; dense autoseg full frames **13.16 s → 8.27 s (1.59×)**, incremental
  frames 1.17×. The `cv2.polylines` rasterizer swap was **stopped** and pinned by
  a test: the field never enables QPainter antialiasing, so 1102 of 1475 lit
  outline pixels differ (max channel delta 255), and per-trace opacity needs a
  blend per trace at 1814 ms against QPainter's 155 ms. (#97)
- **Performance: Feret computed on demand.** `TraceData` no longer retains the
  transformed point array for deferred Feret; it is computed from the live
  `Section` at read time. Bit-exact against the stash path over 293 fixture traces
  and 192 degenerate cases, with `exportTracesCSV` byte-identical on all three
  fixtures. Retained bytes per closed `TraceData` become a constant 392 B at every
  point count (was 648 B at 4 points rising to 16,520 B at 500): on 20k traces ×
  64 points, **30.73 → 7.69 MB (−75%)**; on `class_series`, 3291 → 393 B per trace
  (−88%). A Feret read recomputes and is nonetheless 17-35% faster, because the
  old read paid NumPy-scalar to Python-float extraction per point. `exportAll` now
  calls `saveAllData()` first so Feret columns cannot describe older geometry than
  the rest of their row. (#98)
- **`datatypes`/`constants` import graph is now Qt-free**, verified by subprocess
  tests that run with `QT_QPA_PLATFORM` unset and every PySide6 import raising (a
  real `.jser` opens, loads a section and maps traces both directions with zero
  PySide6 in `sys.modules`). `transform.py` replaces `QTransform` with plain-float
  affine math; `getQTransform`/`fromQTransform` remain as the only Qt adapters,
  lazily imported, and a `Transform` no longer holds a Qt object (pickle/deepcopy
  round-trips tested). The old implementation is kept as a test oracle and compared
  bitwise via `struct.pack` (1 ULP or a signed zero fails): zero mismatches across
  12 matrix-type fixtures, 550 random transforms, 3,600 composition pairs and
  25k-point arrays both directions. One characterized divergence: `QTransform`
  classifies matrices with a 1e-12 fuzz and drops terms below it where the pure
  affine keeps them; a test proves with exact rational arithmetic that the new
  result is the correctly-rounded one, and since `mapPointsArray` already used the
  general formula, this makes `map()` and `mapPointsArray()` agree rather than
  disagree. Performance at parity or better on every operation (`inverted` 3.1×,
  `compose` 3.4×). (#93)
- **Dead grid cut code deleted; 3D transform mapping vectorized.** 100 lines of
  dead knife/cut machinery removed from `grid.py` after independently re-verifying
  the finding, with live `getExterior`/`mergeTraces`/`cutTraces` outputs
  byte-identical across 602 golden cases. `objects_3D.py` Surface/Contours
  per-point `tform.map` loops are batched via `mapPointsArray` (1.4× on the meshing
  path; full `generateVolumes` output SHA-identical across 3 series × 3 modes);
  `Ztrace3D` deliberately stays scalar with the invariant lookup hoisted, since
  per-point tforms and 1-point-per-section fixtures put it 18× below the
  vectorization crossover. 220 equivalence tests written against the scalar path
  before switching, mutation-checked. (#92)
- **Source-install docs state Python 3.11 up front** and recommend uv (which
  auto-downloads 3.11), with plain venv as the alternative, in the README,
  `docs/USER_GUIDE.md` and `CONTRIBUTING.md`. `pip install -e .` fails on a
  Python 3.14 interpreter because the project pins `>=3.11,<3.12`, and the
  requirement was previously stated after the venv step. (#85)
- **CI installs via `astral-sh/setup-uv` + `uv sync --frozen`** and runs pytest
  under `uv run --frozen`, for reproducibility against the committed lock. (#86)
- **Absolute local paths removed from bundled series assets.** Four bundled series
  assets stored a `src_dir` copied verbatim from the machine of the developer who
  made them, including their account name and desktop layout; the same kind of
  path appears in two standalone `assets/misc` scripts where it is a user-entered
  placeholder. These are dev-only test fixtures plus the shipped welcome series,
  and the images those paths refer to are not distributed, so the value serves no
  purpose. `""` is already the supported state: it is the `getEmptyDict()`
  default, it is what `updateJSON` backfills when the key is absent, and
  `create_ng_zarr/utils.py` already substitutes it before hashing because the value
  differs between users. An empty `src_dir` degrades rather than raising — the
  image layer sets `image_found = False` and the window offers to locate the
  images — and the welcome series never used the stored value, since
  `get_welcome_setup()` reassigns it at runtime. (#100)

- **Update-channel labels renamed for clarity**: "Release" → "Stable
  (recommended)", "Pre-release" → "Beta (early features, may be unstable)";
  docs and the rolling-release title synced. Underlying channel values are
  unchanged. (#65)
- **Beta channel now explicitly excludes the rolling build** by tag
  (previously excluded only by ordering), so it can never shadow a curated
  pre-release. Legacy channel values (`stable`/`edge`) still map correctly. (#66)
- **Rolling main builds re-enabled** in CI to supply the Developer channel;
  paused since 2026-06-29, the original conflict with the pre-release channel
  no longer applies. (#67)

- **Default scaled-Zarr name and location.** "Convert to scaled Zarr" now
  defaults to `<series>.zarr` beside the source image directory (was
  `_images.zarr`); the file filter is loosened so a user-chosen name still works.
  (#57)
- **Linux release asset** is named with the normalized PEP 440 version, matching
  the macOS and Windows assets. (#56)

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
- **Restoring "Needs curation" from the log keeps the assignee.** Marking an
  object as needing curation stores the assignee on the object, but the log
  entry carried only the bare event "Mark as needs curation" — so *Series ▸
  Restore object curation status from log* had nothing to recover and wrote
  the status back with an empty User column. The event now records the
  assignee ("Mark as needs curation (assigned to `<user>`)") and the restore
  parses it back out. Unassigned markings log the bare event exactly as
  before, and logs written before this change still restore as they did —
  with the status but no assignee, since none was ever recorded in them.
- **The legacy brightness/contrast migration destroyed named profiles.**
  `Section.updateJSON` folds the pre-profiles scalar `brightness`/`contrast`
  pair into `brightness_contrast_profiles`; it did so by *assigning* a fresh
  single-key `{"default": (b, c)}` dict, which discarded every other named
  profile on that section. The exposure was per-open, not one-shot: `saveJser`
  reads each section file out of the hidden directory verbatim (`fast_loads` of
  the raw bytes) rather than through `Section.getDict`, and `updateJSON` left
  the legacy scalars in the dict it wrote — so a section the user never
  individually edited kept its scalars across a save and met the migration
  again on the next open, and the one after that. Only a section that went
  through `Section.save` dropped them, and that save made the loss permanent.
  The migration now **merges**. Whether the legacy pair may become `default` is
  decided by whether the *file* carried a profiles dict at all, captured before
  the back-fill loop inserts the key — not by comparing values, which cannot
  distinguish a deliberate `(0, 0)` default from the back-filled placeholder.
  No profiles key means a pre-profiles file, whose scalars are its only
  brightness/contrast and become `default`; a profiles dict that is already
  present is authoritative and is never overwritten, though a missing `default`
  is still filled from the scalars. A non-dict `brightness_contrast_profiles`
  is still repaired, which the old wholesale assignment did by accident and a
  bare merge would crash on. Verified by a two-cycle end-to-end open/save test
  rather than inferred. Inherited from upstream, not fork-introduced: the
  migration block is byte-identical between `upstream/main` and this fork.
  (#113)
- **`openJser` locking every section on unpack is characterized, not changed.**
  `openJser` sets `align_locked = True` on every section as it unpacks,
  ignoring the stored value. Checked and deliberately left alone: it carries an
  explicit "lock the section" comment, predates the fork, matches
  `getEmptyDict()`'s `align_locked = True` default, is already documented as
  legal by `test_jser_canonical_format.py`, and is fail-safe — honouring a
  stored `False` would *remove* alignment protection on every open. The
  hidden-directory resume path honours the stored value because it resumes a
  live working directory rather than opening a file, so re-locking there would
  discard a lock the user cleared mid-session. Both behaviours are now pinned
  by characterization tests so they are not "fixed" later. (#113)

- **Minimum Feret diameter was computed as a vertex-pair distance instead of the
  minimum width.** `feret()` returned the smallest distance between an antipodal
  pair of convex hull *vertices*. The minimum Feret diameter is the minimum
  *width*: the smallest gap between two parallel supporting lines. The supporting
  lines through a vertex pair are generally not perpendicular to the segment
  joining them, so the old value is an upper bound on the width and never the
  width itself, except by coincidence.

  The collinear-hull framing this started from was a symptom, not the cause.
  Substituting shapely/GEOS hulls under the same vertex-pair definition fixes
  nothing (26 wrong versus 25 on a 45-case rotated-rectangle sweep) while the
  correct formulation fixes all 45, and the defect fires with no collinearity and
  no rotation at all: the triangle (0,0), (10,0), (5,1) reported 5.0990 where its
  true width is 1.0. Only 3 of 8 gallery shapes passed and all three were
  rectangles or needles, which agree by coincidence.

  **Behaviour change, stated plainly: 271 of 271 closed fixture traces change,
  every one of them downward** (old values are always overestimates — 0
  counterexamples in 12,000 fuzz sets). Median 0.96% on `class_series`, worst
  **45.93%** (`d03sp12` s46: 0.505747 → 0.346575); worst 14.70% on the shapes
  series. **Errors concentrate on thin structures such as spine necks.** Minimum
  Feret is a displayed trace-list column and is exported by `exportTracesCSV`, so
  values previously displayed or exported were too high by these margins.
  **Maximum Feret is bit-identical on all 271** and no other measurement is
  affected.

  Fix: `minWidth(ring)` = the smallest, over hull edges, of the hull's extent
  along that edge's normal. Pure Python, no new dependency; `hulls()` and the
  calipers walk still supply max Feret unchanged, and `hulls()` no longer sorts
  the caller's list in place. Verified against an exact independent oracle over
  12,000 fuzzed point sets and 122 fixture traces with zero mismatches; tests
  written before the fix (39 failed, then 248 pass). Cost: an O(h²) pass, worst
  about 11 µs/trace (1.76× on 10-point traces, 1.08× at 5000); the Feret column is
  off by default, so a 61k-trace series with it enabled pays roughly 0.7 s. The
  pre-fix implementation was byte-identical to upstream, which therefore ships the
  same defect. (#95)
- **Silent trace-loss paths in the series-to-series import are closed.** The rule
  is now: an import may discard a trace only if that trace overlaps something on
  the surviving side, or if a log entry records it as deliberately removed — and a
  discarded trace always leaves behind both a flag and a log entry. Where the
  machinery cannot decide safely, both sides are kept and the disagreement is
  flagged rather than resolved by picking a winner.

  `Section.importTraces` shortcuts a contour on one Boolean per side from
  `getModifiedSinceDiverge` — *"does this side's log mention this contour after
  the divergence point?"*. `True` is positive evidence of an edit; `False` is only
  silence, and three branches treated silence as proof a side was unchanged. Logs
  get trimmed, get rewritten when an object is deleted (`LogSet.addLog` purges
  every prior log for a deleted object), and are suppressed outright while an
  import runs, so anything a previous merge brought in reads as untouched to the
  next one. `(False, False)` discarded the other section's contour whole with no
  geometry compared and no flag; `(False, True)` replaced ours wholesale without
  comparing a single point, overwriting unlogged work out of existence;
  `(True, False)` dropped theirs, correct when we deleted or renamed the object but
  silent destruction when their work simply was not logged. Separately,
  `keep_below="self"`/`"other"` deleted every unfavoured conflict trace overlapping
  a favoured one and then cleared the favoured pool, so the flagging step had
  nothing left to flag.

  One bound remains, unchanged by this work: when the two logs share no common
  prefix (`last_shared_index == -1` — an empty log, a log trimmed on one side, a
  series produced by conversion) the entire history block is skipped silently and
  the import degrades to a plain union in which deletions resurrect. Nothing is
  destroyed, so this is a failure of intent propagation rather than of safety.
  Making the history check fail loudly instead of self-disabling is a separate
  fix. Also deliberately out of scope: making the merge three-way, which
  `LogSetPair` cannot do without a merge base anywhere in the data model.
  `tests/test_import_silent_loss.py`, 18 tests, 12 of which fail on the previous
  code. (#101)
- **The import's overlap threshold was ignored for the traces that matter.**
  `Contour.importTraces` runs two passes: an optimistic walk comparing `self[i]`
  against `other[i]` while they overlap, which used the caller's `threshold`, and a
  nested scan over everything left over, which compared with a literal
  `threshold=0.95`. Pass 2 is the pass that decides the genuinely divergent
  traces — every trace an import between two edited copies actually has to reason
  about — so moving the dialog's "Overlap threshold" slider off its 0.95 default
  had almost no effect, and nothing said so. Both directions did damage: at a
  *stricter* setting (0.99, or 1.0 = "points must match perfectly") non-duplicates
  were merged and, with the default `keep_above="self"`, **the importing series'
  own trace was dropped outright**; at a looser setting (0.91) real duplicates were
  kept as a conflicting pair. Measured with the real overlap primitive: two side-10
  squares offset by `dx` have Jaccard `(10-dx)/(10+dx)`, so `dx=0.2` → 0.961 and
  `dx=0.5` → 0.913 straddle 0.95 from either side. Fixing this also makes the
  one-comparison skip at the top of pass 2 sound, since that skip assumes both
  passes used the same threshold; the invariant is now documented and pinned by a
  test. Local user-column options are no longer dropped on import. (#99)
- **Scissors right-click destroyed the trace when the trace layer was hidden.**
  The scissors tool picks a trace up by deleting it in `scissorsPress` (a raw
  `section.deleteTraces`, not guarded by `@field_interaction`) and relies on the
  right-click completion in `lineRelease` to recreate it via `newTrace` — but
  `newTrace` is wrapped by `@field_interaction`, which is a no-op while the trace
  layer is hidden. A pickup followed by a right-click completion with the layer
  hidden therefore deleted the trace with nothing put back, silently destroying
  the user's work. `lineRelease` now detects whether `newTrace` actually added the
  replacement via the `section.added_traces` delta (the return value carries
  `log_event`, which is forced `False` while scissoring) and restores the original
  picked-up trace when it did not; `autoMerge` and the scissors "Modify trace(s)"
  log are gated on the same signal. Sibling tools were checked: knife
  (`cutTrace`) and `mergeTraces` delete and recreate inside a single
  `@field_interaction` method, so they skip atomically when hidden and never lose
  data — only the scissors split its delete from its guarded recreate across two
  event handlers. Upstream issue #51. (#81)
- **An empty object group raised `TypeError` on save.** `getGroupDict` passed a
  bare `set` through unconverted for an empty group, which raises in orjson and in
  the stdlib fallback, so the save died instead of writing. Members are now sorted
  unconditionally. Pre-existing, not introduced by #102. (#103)
- **A non-string object key made the pretty writer emit a file no parser will
  reopen.** `fast_dumps` passes `OPT_NON_STR_KEYS`, so the compact writer coerces
  `1` to `"1"`; dumping a key on its own did not, and the writer emitted a bare
  `1:` — the save succeeded and replaced the previous good file. Keys now go
  through `_dump_key`, which lifts the coercion out of the compact writer rather
  than reimplementing it, so the two cannot drift. Not reachable from the GUI,
  since every keyed map is keyed by a name that is always a string, but the failure
  mode is a silently unreadable file on data that cannot be regenerated. (#103)
- **Trace tags were sorted only when the user happened to touch the section.**
  `Trace.getList` sorts them, but it only runs for a section that goes back through
  the model, while `saveJser` reads the hidden directory verbatim — so identical
  content produced 26,305 differing bytes on a 33 KB fixture depending only on
  browsing history. Tags are now sorted in `Section.updateJSON`, beside the section
  key order and contour name order already canonicalized there. (#103)
- **The writer's round-trip test asserted nothing.** It compared
  `_semantic(first)` against `_semantic(json.loads(raw))` with `first` already
  being `json.loads(raw)`, so eight mutations that make `saveJser` silently
  discard the audit log, every section flag, every trace tag, the editor list, the
  host tree, the object attributes, the groups or the user columns all passed. The
  case now builds a source carrying all of those, asserts it is genuinely
  non-empty, and compares the saved document against that source rather than
  against another output of the same writer. (#103)
- **The pretty writer invented top-level keys.** For a document missing `series`
  or `log`, the pretty printer emitted both unconditionally, defaulting them to
  `{}` and `""`, so the two output forms disagreed on the key set — the one thing
  `jser_format` guarantees they never do. No saved file is affected, since
  `saveJser` always populates `sections`, `series` and `log` before calling the
  writer, and output for a complete document is byte-identical before and after;
  it is reachable for anything assembling a document by hand. Both keys are now
  emitted only when present, and the top-level members are collected into a list
  and joined with `",\n"` rather than appending separators inline, which removes
  the dangling-comma class of bug rather than patching one instance. Pre-existing,
  from #102. (#106)
- **Latent `KeyError` crash in series-wide operations with the Feret column
  enabled.** Operations such as `copyObjects` update `SeriesData` and insert
  trace-list rows before `field.reload()` swaps in a section containing the new
  traces, so `series.data` can hold a row the live section lacks and
  `section.contours[name]` raised. `getFeret` now returns `None` when the contour
  is absent or the index is past its end; the cell renders blank and refills on the
  next section change, and the CSV writes an empty field rather than a fake 0.
  (#98)
- **"Use UTC time" could not be turned off until restart.** `utc_p()` did
  `False if utc == "false" else True`, which returns `True` whenever QSettings
  hands back a real bool — that is, with the key unset, and for the rest of a
  session after the options dialog writes it, since Qt caches a bool in-process and
  only a fresh process reads the string `"false"` back from the INI. A fresh
  install therefore timestamped in UTC despite `default_settings["utc"] = False`.
  The read now routes through the `settings_store` seam so the typed read agrees
  with `Series.getOption("utc")`. Verified empirically. Pre-fix module was
  byte-identical to upstream. (#93)
- **Collada (.dae) export is detected rather than attempted.** pycollada is
  detected via `importlib.util.find_spec` and the menu item is disabled with a
  "(not installed)" suffix when absent, so frozen builds no longer offer an export
  that can only fail; the runtime guard is kept as a backstop and its message
  reworded to cover packaged installs. `export3DObjects` surfaces the missing
  package with a clear `notify()` and early return instead of an unhandled
  `ModuleNotFoundError`. (#90, #76)
- **The five mesh-export formats had shared one `attr_name`** (`export3D_act`), so
  four silently shadowed the fifth on the widget; each now has a unique name.
  Same class of defect fixed for two menubar `attr_names`
  (`copyscreen_act` → `savescreen_act`, `resetpalette_act` →
  `resettracepalette_act`), and for the Object ▸ Geometry smooth action, renamed
  `smoothobj_act` so it no longer shadows the field Trace submenu's
  `smoothtraces_act` on the shared widget. (#76, #77, #90)
- **The autoseg shuffle guarantee now applies to what is on screen.**
  `next_shuffle_seed` accepts an optional ids iterable and the caller passes the
  overlay's visible label ids (new `ZarrLayer.getPresentIds`), so "always
  reshuffles" is evaluated against the labels the user can actually see, falling
  back to the 1..63 range when unavailable. (#90)
- **Shortcuts help dialog and z-trace labels.** The five View toggles are reworded
  to match the current menu labels and the "viwed" typo is fixed; mid-label
  "z-trace(s)" is lowercased in the field Z-trace menu and the menubar; and the
  menubar's "Toggle show Z-traces" becomes a checkable "Show z-traces" using the
  `(series, "checkbox")` form, synced from `show_ztraces` at build and in
  `checkActions`. Focus mode is disabled when nothing is selected. (#90)

- **Stale trace color in the incremental field render.** `editTraceAttributes`
  copy-replaces traces; a table-refresh `clearTracking()` could leave the
  incremental render's cached trace list holding the replaced object, drawing
  the old color/name/tags/fill while the selection highlight tracked the new
  copy. The cache now self-heals by validating cached on-screen traces against
  their contours (selection-only refreshes keep the fast path). Inherited from
  upstream. (#69)
- **Undo could corrupt or drop traces on Windows with non-ASCII names.** The
  undo-baseline readers (and fallback writer) used the locale codec while
  section files are UTF-8; explicit `encoding="utf-8"` throughout, plus
  same-class fixes for palette CSV and user-columns import/export. (#70)
- **3D Scene-menu auto-refresh checkbox** now resyncs on window activation
  after the option is changed in Series ▸ Options. (#70)
- **Rolling-release CI race:** ref-scoped build cancellation + non-cancellable
  publish phase so rapid merges cannot leave the Developer channel serving an
  older build. (#70)
- **Interop with upstream PyReconstruct restored:** the fast JSON writer now
  escapes non-ASCII (`\uXXXX`) so fork-saved series read correctly in stock
  PyReconstruct's locale-mode readers on Windows; ASCII payloads keep the
  orjson fast path. (#71)
- **Image→zarr conversion CPU bound:** conversion workers no longer inherit
  all-core OpenCV/blosc threading (regression from the 2024 multi-core change),
  so the CPU-usage slider genuinely limits load; default lowered 100%→50%,
  slider gains tick marks and guidance. (#72)

- **Window no longer restores tiny or off-screen across DPI changes.** After the
  display setup changes (e.g. a 1x external monitor and a 2x Retina panel), a
  restored window that is too small or off every screen now falls back to a
  sensible centered default. (#59)
- **Retry transiently-locked saves on Windows.** `os.replace` during a save could
  fail intermittently with `WinError 5`/`32`/`33` when the file was briefly
  locked by another process (seen during background saves on scroll or section
  change). The atomic replace now retries with backoff for those transient-lock
  classes only; genuine errors such as a missing directory still fail
  immediately. (#62)

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

### Removed
- **Developer update channel.** The in-app "Developer" channel and the rolling
  latest-`main` build that fed it (republished on every push to `main` under the
  fixed `prerelease` tag) are removed. The rolling build's recreate-on-every-push
  defeated GitHub's release ordering, so beta testers on builds predating the Beta
  channel's rolling-tag exclusion (v1.21.0-beta-2 and earlier) could be offered
  dev builds. Developers now track `main` with a source install instead
  (README ▸ *From source (developers)*). A stored `developer` channel option
  degrades gracefully to Beta, and the updater keeps its rolling-tag exclusion as
  defense in depth. Reverts the channel added in #66, so the net effect for
  1.21.0 is the same two channels as 1.20.4 — the Developer channel existed
  only between the beta-3 and beta-5 pre-releases.

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

[Unreleased]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.21.0...HEAD
[1.21.0]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.20.0...v1.21.0
[1.20.0]: https://github.com/dustenhubbard/PyReconstruct/releases/tag/v1.20.0

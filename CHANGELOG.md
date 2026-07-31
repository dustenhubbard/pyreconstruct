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

## [1.21.0-beta-6] - 2026-07-30

### Added
- **A keyboard shortcut for "Invert selection".** The field action shipped with a
  right-click row and a working handler but with its shortcut written into the
  source as an empty string, so it had no key, no row in the shortcuts dialog,
  and no entry in `default_settings.py`. It now defaults to `Ctrl+Shift+I`
  (`Cmd+Shift+I` on macOS) and is rebindable like the rest of the set, which
  makes the selection trio read `Ctrl+A` / `Ctrl+D` / `Ctrl+Shift+I`.
  `Ctrl+Shift+I` is the invert-selection key in Photoshop, Krita and Affinity
  Photo, and it is claimed by no system-global binding on Windows, macOS or
  Linux. `Ctrl+Alt+I` was the runner-up and was rejected because `Ctrl+Alt` is
  indistinguishable from `AltGr` on international keyboard layouts. A new test
  additionally asserts that no two *live* actions share a sequence, counting
  actions inside menus and not only those attached to the window, which is the
  case the existing check could not see.
- **Alignments ▸ Import alignments ▸ From another series (.jser).** Importing an
  alignment from a colleague's series was reachable only through Series ▸ Import
  series data ▸ From another series, the eight-tab whole-series merge dialog,
  while Alignments ▸ Import alignments offered only `.txt` and SWiFT. All three
  sources now sit together, with `.jser` first as the common case. The new entry
  runs the same `Series.importTransforms` the merge dialog's Alignments tab runs,
  so the calibration check and the magnification rescaling are unchanged; it just
  skips the seven tabs that are not about alignments. Each row's target name
  prefills from the source alignment's own name, since importing under the same
  name is what users mostly want.
- **A keyboard shortcut for "Copy to sections...".** The action now has a
  user-configurable default of `Ctrl+Alt+C`, listed in the shortcuts dialog next
  to Copy. `Ctrl+Shift+C` was the natural sibling of `Ctrl+C` and was requested
  in review, but it is already **Toggle curation in object lists** and is
  documented as such, so the copy-to-sections key keeps the "C for copy" mnemonic
  on the otherwise unused `Ctrl+Alt` tier rather than displacing a live binding.
  The key is bound through the field only; the trace list leaves it unbound, as
  every other list menu does. A new test additionally asserts that no two actions
  in the configurable shortcut set share a default key. Qt answers such a clash
  by firing *neither* action, which is invisible until a user reports a dead
  shortcut.
- **Hover tooltips on File > Utilities, and room between a menu label and its
  shortcut.** Utilities collects niche, rarely run tools, so each entry now
  explains itself on hover to someone who has never used it; the copy was written
  against the scripts the handlers actually run rather than against the labels,
  and names the artifacts each one produces (`decode.txt`, the coded `.jser`, the
  dated `decoded-` folder). The mechanism generalizes to any menu: `newAction`
  takes an optional fifth tuple element, the tooltip, and opts the containing menu
  into `setToolTipsVisible(True)` whenever it sets one, which is required because
  `QAction.setToolTip()` alone shows nothing in a `QMenu`. Opting in only when a
  tooltip is set matters, since a `QAction`'s tooltip otherwise defaults to its
  own label and every item would sprout a tooltip repeating what it already says.
  Separately, the widest label in a menu ran into the shortcut column, measured at
  5.5 px of gap on the default macOS theme against 18.5 px of left padding. A
  `QProxyStyle` now pads the gap. A stylesheet rule was rejected on measurement:
  any `QMenu::item` rule swaps the item to the CSS box model and strips the native
  left padding with it, moving the label ink from x=18.5 to x=0.5. (#125)
- **A documentation site built from `docs/`.** A MkDocs Material configuration at
  the repository root renders the existing user guide, the uv development notes
  and a performance summary as a searchable site with a light/dark toggle,
  deployable to GitHub Pages. Additive only: the GitHub wiki and the in-app Help
  link are untouched, and no existing document moved. (#44)
- **`MainWindow` is constructible headlessly, and the menus are now verified
  through a live window.** `MainWindow.openSeries` raises three prompts to finish
  opening a series that is missing something (images not found, no series code, an
  unexpected editor), and under `QT_QPA_PLATFORM=offscreen` there is no window
  manager and no user, so each one spun a modal event loop that nothing ever
  dismissed. That is a permanent stall rather than a slow dialog, and it is why
  the window itself had never been covered. Each site was confirmed to stall on
  its own, with the other two stubbed and `faulthandler.dump_traceback_later`
  reporting where the process was parked. A `main_window` fixture now yields a
  live window over a real series, and 29 tests walk the menus it actually builds.
  The menu tests that existed read the *definition* the menu functions return and
  never ran `populateMenu`, so they could not see a menu dropped on the way to the
  widget, a row wired to a different `QAction` than the attribute that gates it,
  or a shortcut whose option lookup came back empty. (#140, #152)
- **A data-integrity check that runs after destructive operations.** The three
  worst defects found in this cycle were all silent data loss, and in all three
  the suite was green while the defect shipped: the section list deleting a file
  and then raising, the trace attributes dialog erasing tags, and the undo
  baseline being written into the bundled assets. A unit test asserts what a
  function returns, and none of the three changed what any function returned. What
  each of them broke was a property of the series. `check_series` opens a real
  series, performs destructive operations on it, and collects every violated
  invariant together rather than stopping at the first, so one failure reports
  everything that is wrong. (#143)
- **A test that a configurable shortcut reaches the action it is listed for.** A
  shortcut has to agree in three places (a default in `default_settings.py`, a row
  in the shortcuts dialog, and the third element of the action tuple that
  `newAction` turns into `QAction.setShortcut`) and only the third binds anything.
  Two disagreed, and both were user-visible: `Set hosts...` is documented in the
  dialog with `Ctrl+Shift+H` and that key has never done anything, and `Set view to
  image` accepts a rebind that is stored and then silently discarded. (#158)
- **Real-widget selection tests for the four sibling data lists.** Each of the
  trace, z-trace, flag and object lists is built as the real widget over a
  writable copy of the checked-in `class_series.jser`, a real row selection is
  made through the widget's own selection model, and `getSelected()` is asserted
  to return one de-duplicated, order-preserving entry per selected row. Per-widget
  rather than helper-only, because every list overrides `getSelected()` and maps
  rows to a different payload through a different surface, and the object list is
  the one model-backed list, a lazy `QAbstractTableModel` behind a `QTableView`. A
  regression in any of those mappings is invisible to coverage of the shared
  helper alone. (#123)

### Changed

- **The startup update check is now on by default, and existing installs are
  corrected once.** `update_check_on_startup` defaulted to `False`, and
  `Series.getOption` persists a default the first time it is read, so every
  machine that had ever launched the app already had `False` stored and a new
  default could never reach it. The stored value was not a choice, it was a copy
  of the old default, so `backend/settings_migrations.py` overwrites it exactly
  once and records that it has, keyed on the presence of a marker in the same
  settings scope. A user who turns the check off afterwards is never overwritten,
  the option is written before the marker so a failed write is retried rather
  than recorded as done, and nothing on that path raises. The check itself is
  unchanged: it runs only in the installed app, once per 24 hours, and swallows
  every failure. Testing it in the on state also turned up a defect worth naming:
  a timestamp dated in the future read as "checked recently" forever, silently
  disabling the check while the setting still showed as on, reachable by any
  machine that wrote the stamp before its clock synced.
- **The first-run welcome now says the app checks for updates, and that a Beta
  channel exists.** Nothing pointed anyone at either setting. The note appears
  only on the welcome framing, and only in the installed app, since a checkout
  never runs the check and the claim would be false there. The generic fallback
  body no longer opens with "Thanks for updating" on a first run.
- **Importing an alignment onto a name already in use now asks instead of
  refusing.** The importer previously rejected any target name the series already
  had ("Alignment name already exists in current series"), which left no way to
  replace an alignment short of renaming the new one. It now lists the alignments
  that would be replaced, states that the replacement happens on every section and
  that undo will not recover the old transforms, and proceeds only if the user
  confirms. The prompt fires only when a name really is taken, so an import that
  adds new alignments is unchanged. Palettes and brightness/contrast profiles keep
  the old refuse-outright behavior; overwriting those was not asked for and they
  are not undoable either.
- **The "Copy to sections" picker suggests real sections from the open series.**
  The dialog's hint and input placeholder were a fixed `10-20` / `5, 8, 11`, which
  meant nothing in a series that does not run to 20. They now show the series' own
  range plus three sections sampled from it, and the hint text is shorter. Samples
  are drawn from the sections that actually exist, so a series with gaps is never
  offered an example that the picker would then reject.
- **The lint gate now covers the bundled helper scripts, and the dev-only ones
  stop shipping.** `ruff.toml` excluded `PyReconstruct/assets` as "not on any
  import path", while `package-data` shipped `assets/**/*`: all 18 `.py` files
  under `assets/` went into every wheel and installer, and CI opened none of
  them. That is how `assets/misc/zarr_to_jser.py` reached users carrying a
  `SyntaxError` and a `C:\path\to\...` constant, and `jser_to_zarr_v2.py` still
  carries the same hardcoded placeholder. Dropping the exclusion took no code
  change: the critical-error set (`E9`, `F63`, `F7`, `F82`) already passes clean
  over the whole tree. Separately, three asset directories with no runtime
  consumer are now excluded from the wheel and the installers: `assets/misc/`
  (standalone scripts whose `tif_to_zarr` launchers still point at the `src/`
  layout retired in 2023), `assets/scripts/img/` (`mask.py` needs `colorama`,
  not a runtime dependency, so the shipped copy could never run), and
  `assets/scripts/contours_from_labels/`. They stay in the repository, stay
  linted, and keep working from a checkout through `dev/scripts/`. Everything
  the app imports or launches still ships, verified against an installed wheel.
- **`ruff check` is a blocking CI gate.** `ruff.toml` selects the critical-error
  set only (`E9`, `F63`, `F7`, `F82`: syntax errors and undefined names) and a
  `lint` job in `test.yml` enforces it. The tree passes that set clean, so the
  gate landed at zero diff and started protecting immediately. It is deliberately
  not the full default set, which reports several thousand findings on this tree,
  roughly 79% of them whitespace, unused imports and import order, and would mean
  a four-thousand-line diff across 173 files conflicting with every open branch.
  A `tests/conftest.py` and a root `Makefile` land alongside it. (#111)
- **`gitpython` bumped to 3.1.57 and `vtk` to 9.5.2, off twelve published
  advisories.** An OSV scan of all 106 resolved packages, the full transitive set
  from `uv.lock` rather than the 20 direct pins, found vulnerabilities in exactly
  these two. `gitpython==3.1.50` carried nine HIGH advisories, all of them
  command-injection or argument-injection paths through clone options, config
  section names, `expandvars()` and `git diff --output`; `vtk==9.4.2` carried
  three CVEs. (#130)
- **The test suite no longer writes to the machine's real application settings.**
  Running the suite modified the maintainer's own preferences three times in one
  night, through three separate routes: a fixture calling `QSettings.clear()` and
  rewriting `allKeys()` (on macOS `NativeFormat` is `NSUserDefaults`, and
  `allKeys()` on an app domain also returns the global domain, so the rewrite
  copied 67 system defaults into the app's plist), a test assigning `series.user`
  (whose setter addresses the machine-wide scope and overwrote the stored
  username), and every `main_window` fixture build prepending a pytest `tmp_path`
  to `recently_opened_series`. Three routes in one night is a pattern rather than
  three accidents, so the whole suite's `QSettings` are redirected at the session
  level: a rule that cannot be forgotten rather than one that has to be
  remembered. The two recent-series tests additionally get their own store, since
  `recently_opened_series` resolves to one machine-wide slot shared by every
  process on the box, which made their result a property of the machine. (#157,
  #162)
- **A missing `pytest-qt` now fails the run instead of quietly dropping the widget
  tests.** `pytest-qt` is declared in the `test` extra rather than in
  `dependencies`, and it is the only source of the session-scoped `qapp` fixture
  the real-widget tests are built on. A `.venv` synced without `--extra test`
  therefore had `pytest` but not `pytest-qt`, and both gui modules guarded
  themselves with a module-scope `pytest.importorskip("pytestqt")`, so they
  removed themselves from collection rather than failing: 4228 tests collected and
  green became 4157 collected and green, exit 0 either way. The marker is now the
  sanctioned mechanism and a guard test forbids the module-scope `importorskip`
  that hid the gap. (#145, #164)
- **The suite clears the latched keyboard modifier between tests.**
  `QApplication.keyboardModifiers()` is process-wide, so a test that leaves a
  modifier held changes what a later test sees, through state no test can inspect.
  The menu suite is green today under any file-level ordering but not under a
  test-level reordering, which is a latent flake rather than a passing suite. A
  fixture now resets the latch. (#163)
- **Stable releases are staged as drafts and pre-releases publish immediately.**
  The draft step is an asset-completeness gate that catches a matrix leg which
  failed to attach its installer. That protection matters most for a stable
  release, which reaches every user; for a beta it is friction, since testers
  should get the build without a manual publish. One global variable previously
  served both, so the correct value depended on which kind of cut was next and had
  to be flipped back afterward, which was a standing hazard. The decision is now
  computed once from the tag, in the existing classify step, so the publish and
  prune steps can no longer disagree. `STAGE_RELEASE_AS_DRAFT` survives as a
  three-state override for staging a beta deliberately. (#109)
- **The test workflow's actions moved off the Node 20 runtime, and are pinned by
  commit SHA.** GitHub annotates `actions/checkout@v4` and `astral-sh/setup-uv@v5`
  as Node 20-deprecated and force-runs them on Node 24. The annotation predates
  this cycle and is harmless today, but it becomes a hard failure the moment Node
  20 support is withdrawn. Both move to the newest floating major that declares
  `node24` natively, and every major crossed was read rather than assumed. (#119,
  #123)
- **Five documentation claims that an action cannot be undone are corrected.** The
  `WARNING: This action cannot be undone.` dialog stopped appearing on object
  attribute edits and on stamp radius and shape edits when those actions were
  given real undo states, and the warning was deleted from them in the same
  commit. The documentation was never updated, so the manual still told users that
  editing attributes or a radius was unrecoverable, and that Undo and Redo would
  not reach anything done through the object or section list. Tests now pin which
  actions really do warn, so the documentation and the code cannot drift apart
  again silently. (#134)
- **Two benchmark figures the implementation overturned are retracted in place.**
  `benchmarks/REPORT.md` is cited when performance decisions are made, and two of
  its forward-looking figures did not survive being implemented, so anyone citing
  the document was citing numbers that had inverted. The correction is by
  annotation, with the original text struck and the measurement that replaced it
  beside it, because a silently edited number teaches nobody why it was wrong. The
  `cv2.polylines` speedup is the larger of the two: the 22-26x came from a script
  drawing every trace in one call in a single color with no opacity, while the
  real draw loop varies color, pen width and opacity per trace and so needs a
  blend per trace, on which the OpenCV path measures 1814 ms against QPainter's
  155 ms. (#114)
- **The macOS thread-cap notes carry measured CPU numbers, and the thread-pin
  check xfails there.** `cv2.setNumThreads()` is a no-op under Apple's Grand
  Central Dispatch and `getNumThreads()` reports the CPU count, so the pin check
  cannot pass on macOS and no environment variable caps it either, since GCD reads
  none of the OpenMP/OpenBLAS/MKL variables the cap sets. The assertion is left
  unweakened because it is correct on Linux and Windows, and `strict=True` means
  an OpenCV build that becomes cappable turns the test red and gets the marker
  removed. The marker text originally asserted two consequences that were reasoned
  rather than measured, and both were wrong on this build; they are replaced with
  per-operation numbers taken from the shipped converter invoked exactly as the
  GUI invokes it. (#110, #112)

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
- **A locked object's traces could be cut, moved, renamed and split.** Reachable
  through the ordinary interface and silently destructive: select a trace, turn on
  focus mode, tick `Locked` on that object's row in the object list, page to the
  next section, press `Ctrl+X`, and the object's traces on the new section are
  deleted with no message while the object is still locked. Ticking `Locked` used
  to make that safe, because both lock entry points deselect everything and
  `Section.addSelectedTrace` drops a trace whose object is locked, so the
  selection normally cannot hold one. Paging undoes it: `changeSection`
  repopulates the selection from `focus_mode` by assignment rather than through
  `addSelectedTrace`, and neither lock entry point clears focus mode. That refusal
  in `addSelectedTrace` was the only lock check on these paths; each one read the
  selection and mutated it, relying on the selection never containing a locked
  trace instead of checking, and the assumption was never stated anywhere a reader
  would find it. Six operations now check for themselves through one shared
  `refuseLockedTraces`: cut, paste attributes, the arrow-key translate, the knife,
  the pointer drag, and the focus-mode split and incorporate. Each reports rather
  than refusing silently, because a silent refusal reads as a dead shortcut. The
  drag is checked at the release rather than at the start, since `notify` is modal
  and raising it mid-gesture with the button held would block the gesture it is
  reporting on, and unhiding the traces already restores their position, so a
  refused drag snaps back. In the other direction, hide and unhide no longer check
  the lock at all: hiding changes what is drawn, not what is measured, and every
  point, name and tag survives it. Selection itself is untouched, so the ordinary
  way of selecting a locked object's trace still does nothing. (#166, #168)
- **Remove duplicate traces ended in `ZeroDivisionError` on a real working
  series.** Reported from `1.21.0b5` on Windows: the operation stopped, nothing
  was cleaned up, and the dialog went away. `Trace.getOverlapRatio` rasterizes both
  traces into a fixed-size mask and picks the raster scale from the area of their
  combined bounding box, which collapses to zero when both traces lie on the same
  vertical or the same horizontal line. Two collinear segments, a single point and
  a run passing through it, or a three-point trace whose points share an `x` all do
  that, and degenerate traces of that shape are expected in real data. The only
  caller does not catch it, so the exception took the whole pass down on the first
  such pair and the remaining sections were never scanned. The function now
  returns 0 for a combined box with no area: two traces confined to one line have
  no area in common to measure, so 0 is the honest answer, and it reads as "not a
  duplicate" at every threshold the callers use. Degenerate traces that really are
  duplicates are still cleaned up. (#167)
- **Renaming an object to the name of its host crashed and left the series
  unopenable.** Renaming a traveler to its host's name, renaming a host and its
  traveler to one name in a single edit, or renaming an object to the name of its
  grand-host raises `RecursionError` partway through `Series.editObjectAttributes`.
  The object's group memberships and `obj_attrs` have already been copied onto the
  new name by then but no trace has been renamed, so both names exist and both
  carry the attributes. The saved file is the worse half: the crash leaves a
  self-host edge in the tree, `getDict()` writes it out as `{"square": ["square"]}`,
  and `HostTree.__init__` raises `RecursionError` on that dict. The app keeps
  running after the crash, so a user who saves afterward gets a `.jser` that cannot
  be opened again. `HostTree.getHosts` and `getTravelers` recursed over neighbors
  with no visited set, and `renameObject` created the cycle by reading the old
  name's relationships, removing the old object, then re-adding them under the new
  name. Cycles are now refused in `HostTree.add` rather than tolerated. This is not
  a new rule: `setHosts` and the field's host-assignment drag already refuse both
  the self-host and the mutual-host cases and say so, but those are caller-side
  checks that a path could simply not repeat, and `renameObject` was such a path.
  Traversal additionally became iterative with a visited set, because a file
  written before this fix can already contain a cycle and traversal has to survive
  one to get far enough to repair it. (#147)
- **A repeated or unknown section number half-deleted a series.**
  `Series.deleteSections` was a bare loop removing a file and a dictionary entry
  per requested number, with the z-trace repointing after the loop, so any raise
  partway through left a series that was half deleted and unrecoverably so: the
  section list has already shown its no-undo warning and saved by the time the
  datatype runs. A repeated number produced exactly that, because the second copy
  reached an entry the first had removed. Measured on a copy of `shapes1.jser`,
  `deleteSections([2, 2])` raised `KeyError` with sections 0, 1, 3, 4 remaining and
  every z-trace still carrying a point on the section that no longer exists, which
  the next save writes back out. The z-traces are the damage, and they are damaged
  precisely because the repointing loop sits after the delete loop and never ran. A
  section number the series does not have did the same to everything ahead of it in
  the list. The request is now normalized once, at the top: repeats collapse with
  first-seen order preserved, and an unknown number raises before anything is
  removed rather than at whatever position it happened to occupy. (#151)
- **The trace attributes dialog erased tags on a mixed selection.** Select two
  traces of the same object carrying different tags, open the attributes dialog,
  press OK without touching the tags field, and both come back with no tags at all.
  Nothing warns, and the tags field looked empty the whole time, so there is no
  reason for the user to suspect the edit touched tags. `TraceDialog` folds a
  disagreeing selection down to one displayed value per field, using `"*"` for the
  name and `None` for color, points and both halves of the fill mode; for tags it
  used an empty set. `Section.editTraceAttributes` reads `None` as "leave this
  alone" and an empty set as a real value, so it assigned the empty set to every
  trace in the selection. Tags were the one field of the five whose "no single
  value" sentinel was not the one the consumer recognizes. The empty set could not
  simply become `None` at the consumer, because an empty set is the legitimate way
  to say "clear all tags" and is exactly what `Remove all trace tags` sends. The
  producer is repaired instead: the dialog records that it blanked the field for
  lack of a single value and returns `None` rather than an empty set when the field
  is still blank on confirm. A field the user actually emptied is unaffected. (#136)
- **The object attributes dialog could not remove a tag.** Deleting a tag from the
  Tags field and confirming did nothing, and clearing the field entirely did
  nothing, on every selection. `Series.editObjectAttributes` called through with
  `add_tags=True` unconditionally, and under that flag the consumer iterates the
  incoming set and adds each element to the trace's own tags. So a set with one tag
  deleted is indistinguishable from the same set with it present, and an empty set
  is an empty loop: only the assigning branch can remove. The dialog pre-fills the
  field from the object's real tags for a single-object selection, so it showed
  real tags, accepted an edit, reported the edit back, and the edit was then
  discarded, with nothing warning and nothing logging a difference. (#141)
- **The object comment editor blanked comments on a multi-selection, and "Merge
  attributes only" crashed.** Both came out of an audit of the bug class behind
  this cycle's two data-loss defects: an empty or absent collection carrying a
  different meaning at the producer than at the consumer. `editComment` blanked its
  field whenever more than one object was selected, on selection size alone and
  never on the values, and the blank was then written onto every selected object.
  The `Merge attributes only` action sent `merge_attrs=True` where the keyword is
  `merge_attrs_only`, so both copies of the action crashed. A third instance is
  fixed in the same pass: a blank opacity field in the 3D edit dialog returns
  `None`, which the sibling attribute setter reads as "leave it alone" while
  `SceneObject.setAlpha` takes the same `None` unguarded, corrupting state and then
  crashing with the 3D scene open. The audit ran four passes, three of them AST
  rather than grep, because the half of the class where `None` is used as a
  container is not greppable; the pass that mattered was the one with guard
  suppression turned off, which catches a guard sitting *after* the use or
  inverting its sense, and all three latent defects came from it. The passes were
  calibrated against `upstream/main`, where both already-known instances are
  detected by the pass meant to detect them. The mechanical reason tags broke while
  color and fill did not is that `int`, `float`, `color`, `file`, `dir` and `shape`
  fields all return `None` when blank, and only `multitext` and `multicombo` return
  an empty list. (#142)
- **A regex typed into an added filter row was silently replaced by another
  object's name.** `MultiInput` builds each initial combo row honoring the field's
  `restrict_to_opts`, but the `+` button's slot left `allow_new` at its default of
  `False`, so in a permissive field the first row accepted free text and every row
  added afterward did not. The symptom is a substitution rather than a rejected
  keystroke: `CompleterBox.focusOutEvent` does not clear an out-of-list entry, it
  replaces it with the current completion or, failing that, the first item in the
  drop-down. Typing a regex into an added row and tabbing away turned it into the
  alphabetically first name in the list, and the dialog then reported that name as
  though the user had picked it. The dialog's own validation cannot catch this,
  since it only checks membership when `restrict_to_opts` is set, which is exactly
  when the substitution is correct. Five fields change behavior, all of them regex
  filters: the two on `Add to Scene`, the two on the `Import series` traces tab,
  and the one on its z-traces tab. (#135)
- **Opening the welcome series wrote into the application's own bundled assets.**
  Launching from a source checkout left the working tree dirty, with
  `assets/welcome_series/.welcome/welcome.0.s0` changed from the committed `{}` to
  a full section file. The welcome series is opened in place from the install tree,
  so its hidden working directory and its installation are the same directory,
  which is true of no other series: every other one gets a hidden directory created
  fresh beside the user's `.jser`. `SectionStates.initialize` writes an undo
  baseline into that directory on open, and for the welcome series that path
  resolves onto the shipped file. (#137)
- **Removing a row from a multi-value field left the dialog too tall.** Pressing
  `-` on a `multitext` or `multicombo` field gave the row's height back a press
  later rather than on the press that removed the row, so a band of unused space
  opened inside the dialog and every further `-` moved that band rather than
  closing it. The dialog never got back to the size it had for the same number of
  rows on the way up: five rows down to one measured 262, 233, 204, 175, 146
  against a one-row height of 146, ending 29 px (one row) high throughout, and the
  same sequence on `cocoa` behaved identically, so it is not an offscreen artifact.
  The cause is a stale size hint rather than a stale minimum size. Removing the
  widget marks the layouts dirty and posts a layout request that Qt delivers only
  after the slot returns, so both the field's hint and the host's still described
  the layout with the removed row in it and `adjustSize()` resized to the previous
  row count. Setting the window minimum to zero, activating only the host's layout,
  and three further geometry calls each changed nothing; activating the field's own
  layout and then the host's produced the correct sequence, and that is the fix.
  Nothing is deferred and no offset is applied: the resize still happens inside the
  slot, it just gets a current hint to resize to. The `+` direction was measured in
  the same pass against a report that it clipped the new row, found not to clip,
  and its asymmetry with `-` pinned as correct rather than patched. (#161, #155)
- **`Series.removeObjAttrs` no longer raises on a name with no attributes entry.**
  The unconditional delete becomes a `pop` with a default. No reachable path
  changes: the one call site is preceded on the line above by an `addLog` that
  writes provenance as a side effect and creates the entry the next line deletes,
  for an object that may never have had one. That guarantee is conditional, holding
  only while the object name is truthy and a user is set, which is why the
  invariant the delete was standing in for is now pinned by a test rather than left
  implicit. (#160)
- **Four optional-collection defaults now behave the way their docstrings say.**
  The same class as the reachable defects above: a parameter documented as
  optional, defaulting to `None`, then dereferenced as a container. In three of the
  four the guard exists but sits after the use or inverts its sense, which is why
  reading the guard alone says the code is fine. On its own documented default,
  `ObjGroupDict.__init__` raises `AttributeError` four lines before its guard,
  `seriesToLabels` raises `TypeError` before its guard (leaving the branch that
  reads the window back off the zarr dead), `Series.importTraces` raises `TypeError`
  on its section range, and `optimizeSeriesBC` optimizes zero sections silently.
  None is reachable today, since every caller supplies a real value, and each was
  re-verified independently by calling it with its own default and walking its call
  graph rather than by trusting the earlier report. Two further reported instances
  were checked and deliberately left alone. (#146)
- **A version's release notes are shown once, on the first launch of that version,
  instead of twice around every update.** Two independent paths put notes on screen
  for the same version: the update prompt rendered the GitHub release body for the
  *remote* version, and the What's new dialog rendered the bundled notes for the
  version now running, gated on a stored last-seen version. Nothing connected them,
  so taking an update meant reading the notes at the prompt and reading them again
  on the next start. Only the second showing describes what the reader is actually
  running; the first describes a version they have not installed and may decline,
  and it competes with the update offer itself for attention. The notes body is
  therefore removed from the update prompt, which keeps the version, channel,
  download size, a link to the release notes and a line saying the notes appear on
  first open. Declining and taking the update a week later behaves the same, since
  the prompt writes nothing and the stored version is unchanged. (#169)
- **Undoing a focus-mode trace split produced a duplicate trace.** Reported
  upstream: shift-clicking a trace in focus mode to split it out as `<obj>_split`
  and then undoing left two traces, one under each name. The focus-mode split
  branch mutates the section and then only regenerates the view; it is the only
  caller of `editTraceAttributes` in the GUI that neither carries the interaction
  decorator nor saves a state itself, while its sibling branch three lines below,
  the incorporate-into-object merge, does. The duplication follows from which
  contours undo restores: with no state recorded for the split, the current state
  is still the one written by the previous edit, so its modified set names that
  edit's contours and cannot name the split's. (#129)
- **`Trace.fromList` consumed the list it was given.** Inherited from upstream
  byte for byte rather than fork-introduced. A whole-package parse gate landed
  alongside it, walking all of `PyReconstruct/` with builtin `compile()` rather
  than `py_compile` (which would write bytecode into the source tree for every
  non-imported script it touched) and reporting every offender in one assertion.
  191 files, well under a second. The gap it closes is real: a standalone script
  that no module imports is parsed by nothing, so a syntax error in one could reach
  users and be found first by a user following the autoseg workflow. Parsing is not
  importing, and the gate says so; syntactic validity is the floor, and the floor
  was missing. (#118)
- **Two degenerate-input crashes are guarded.** `Grid.getExterior()` raised
  `ValueError` on a contour that keeps no anchor points, because the anchor lookup
  returns a shape-`(0,)` array against which a two-element shift cannot broadcast.
  It now skips such a contour: with no anchor points there is no exterior to emit,
  and appending an empty one would only relocate the crash, since both public entry
  points feed every exterior straight into a reducer that rejects an empty array.
  This is a latent crash in a public method rather than a reproduced user-facing
  one: a sweep of about 50,000 randomized traces produced 51,756 contours and no
  anchor-free one, and that sweep is pinned so a future change to the line drawing
  that does produce one is caught. Separately, the trace list's contour lookup was
  unguarded across the same desync window that crashed the Feret columns. The list's
  rows come from the series data rather than from the section it is displaying, and
  a series-wide operation writes its sections, repaints the lists, and only
  afterward swaps in a section object containing the new traces; between those two
  steps a row can name a trace the displayed section lacks. Every trace-list
  context-menu action goes through that lookup. (#121)
- **Recovering a series whose images moved built a doubled path.** When a series is
  opened whose image directory no longer resolves, the open path probes for an
  image file beside the `.jser` and, on a hit, passed that *file* to
  `changeSrcDir`, which documents its argument as the new image *directory* and
  assigns it straight through. Joining the section's own filename onto it then
  produced `/tmp/imgs/shapes_0.tif/shapes_0.tif`, which resolves to nothing. The
  recovery also marked the series modified before anything could check whether the
  images had actually reloaded, and passed `notify=False`, so the failure was
  silent. The shipped checker fixture reproduces the trigger. (#115)
- **The data lists returned one item per selected cell rather than one per selected
  row.** All five lists are multi-column tables with item selection, so a row-wise
  selection returned each item once per selectable column: on a 198-section series
  with five selectable columns, selecting one row returned five entries and
  inverting the selection returned 990 instead of 198. Actions that require exactly
  one item rejected a single selected row with "Please select only one section".
  De-duplicated by row, order-preserving, in one shared helper on the base table.
  (#117)

### Removed
- **The two `tif_to_zarr` launcher scripts.** `PyReconstruct/assets/misc/`
  shipped a `tif_to_zarr.sh` and a `tif_to_zarr.bat` whose whole job was to
  activate a virtualenv and run `src/assets/misc/tif_to_zarr.py`. Neither half of
  that has existed since November 2023, when `src/` was renamed `PyReconstruct/`
  for the pip-installable layout and the dev environment moved to `uv`'s
  `.venv`: the shell version fails on line 4 at `env/bin/activate` before it ever
  reaches the missing path. The `.sh` also never located itself, so its
  `cd ../../..` was relative to whatever directory the user happened to be in.
  Nothing referenced either file (not the docs, the manual, the README, `dev/`,
  the packaging spec, or the suite), and the job they front is now done in the
  app by `Series > Images > Convert to scaled images`, which additionally
  writes the multiscale layout the field renderer prefers. Repairing a string in
  each would have left two files that still could not run, so they are removed
  and `tif_to_zarr.py` documents its own invocation instead. The script itself
  stays and still works from a checkout.
- **The bundled `assets/misc/zarr_to_jser.py` script.** A hand-edit-the-constants
  developer script that imported a label zarr back into a series. It could not run
  against anything the app produces: it read a `srange` zarr attribute that no
  current code writes (`seriesToZarr` writes `sections`), and it called
  `Section.addTrace(log_message=...)`, a keyword that signature no longer has. Its
  only producer, `assets/misc/jser_to_zarr_v2.py`, has drifted the same way. The
  job is done by `labelsToObjects` in
  `PyReconstruct/modules/backend/autoseg/conversions.py`, reached from the field
  right-click "Import labels" and the zarr palette's "Import Contours" button,
  which additionally handles a downsampled labels array, per-id selection, the
  curated color palette, and group assignment. The import-resolution test that
  guarded the deleted file now covers every script in `assets/misc/` instead.

### Fixed
- **Importing transforms adds the new alignment to the alignment menu.** Both
  `Alignments > Import alignments` entries, `From .txt file...` and
  `From SWiFT project...`, create an alignment and make it the current one, and
  neither rebuilt the menus afterwards. The created alignment was missing from the
  field's "Series alignment" submenu, which went on showing the previous alignment
  as the checked one. The current alignment then had no menu action of its own, and
  `changeAlignment` looks one up by name for the alignment it is leaving, so the
  next alignment switch by either route (the submenu, or "Edit alignments...")
  raised `AttributeError` and put up an error report instead of switching. Both
  imports now rebuild the context menus, and only when the set of alignment names
  actually changed.
- **Importing alignments from another series is now undoable.** The Alignments tab
  of Series > Import series data > From another series rewrites `section.tforms`
  on every section in the series, and there was no way back: `importTransforms`
  took a `series_states` argument, the caller passed one, and the method never
  forwarded it to `enumerateSections`, so no undo state was recorded anywhere. It
  now records the same unbreakable series-wide state the `.txt` importer and
  `Series.modifyAlignments` already record, so one undo restores every section's
  previous transforms, and a redo re-applies the import. The state is deliberately
  unbreakable: a per-section undo would leave the imported alignment on some
  sections and not others, which `Series.alignments` rejects as corrupt. Measured
  on the 198-section `class_series` fixture, recording the states costs about
  20 ms on top of a 60 ms import.
- **Renaming or deleting a brightness/contrast profile is now undoable.** `Series >
  Brightness/contrast profiles...` rewrites `section.bc_profiles` on every section
  in the series, and there was no way back. `MainWindow.changeBCProfiles` passed
  the undo states to `Series.modifyBCProfiles`, which had no such parameter, so the
  object bound to `log_event` instead: truthy, so nothing raised, logging happened
  by accident, and no undo state was recorded. One undo now restores every
  section's profiles and the profile the series was displaying, and a redo
  re-applies the change. Brightness and contrast adjustments themselves are still
  not undoable, deliberately: the profiles are stored on the series undo state
  rather than in `FieldState`, so an unrelated undo cannot revert a slider nudge.
  Measured on the 198-section `class_series` fixture, recording the states costs
  about 26 ms on top of a 67 ms rename.
- **Renaming or deleting the brightness/contrast profile currently on screen no
  longer raises.** `Series > Brightness/contrast profiles...` rewrote every
  section's profiles and then reloaded the field before switching profiles, so a
  rename left `series.bc_profile` naming a key that no longer existed.
  `Section.brightness` indexes `bc_profiles` by that name and the reload reads it
  through the brightness/contrast palette, giving `KeyError: '<old name>'` on the
  forward path, with no undo involved. The displayed profile now follows the
  rename, and deleting it falls back to `default`.

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
  (113 actions and 32 submenus, separators included) is now frozen by
  `attr_name`, and the File and Series menus are additionally frozen label for
  label, so a future pass has to name anything it drops, moves or renames.
- **Data clean-up menu.** A "Clean up" submenu under the Series menu groups three
  series-wide maintenance operations, each a single undoable action with a
  progress bar over the existing `enumerateSections`/`SeriesStates` path: *Remove
  duplicate traces* (same object name and geometrically coincident on the same
  section, exact points or IoU above a threshold, default 0.95; never merges
  distinct objects), *Remove pixel-dust traces* (small closed traces at or below a
  user-chosen threshold, presented in a reviewable `PixelDustDialog` before
  anything is deleted), and *Remove empty traces* (degenerate geometry only: no
  points, zero-area closed, zero-length open; after a count-stating
  confirmation). Locked objects are left untouched. `MalformedContoursDialog` is
  generalized with an overridable column/heading spec so the review dialog reuses
  its selection/navigation/delete/export behavior. (#88)
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
  stability are unchanged. The Series ▸ Options seed field is relabeled with a
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
  the objects appear on. One undoable operation, no per-object full-series scans.
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
  on-disk format: byte invariants, the hidden unpack directory, the top level and
  the holes in the sections array, the log's pseudo-CSV rules, every positional row
  documented index by index, the options bag and settings scoping, and the
  migration branches in `updateJSON`. Roughly 120 machine-checked `file:line`
  anchors, and a minimal example extracted from the doc itself that opens
  headless, deep-equals after save and round-trips byte-identically. Also lists
  the reader/writer divergences found while documenting. (#94)
- **`benchmarks/` measurement harness (Phase 0).** Replaces the withdrawn RAM
  figures and assumed hotspots with measurements. Cold and warm are explicit
  labeled conditions and never pooled; the harness observes which path
  `openJser` took and aborts on a mislabeled rep; loud manifest with hard-fail on
  missing files, uniform warmup, rotated checkout order, page cache pinned; guards
  verified by negative test. Corrected numbers (3 reps, medians): warm-vs-warm
  2.05× / 2.39× / 2.55× at 162k/324k/485k traces; cold-vs-cold 1.44-1.48×, of
  which roughly 20% of the cold spike is fork-attributable and 80% the shared
  JSON-parse/unpack path. Reading all 636 section files is 0.30 s (0.6%), so the
  file choreography is not I/O; JSON decode 15.7%, object construction 30.7%,
  geometry 53.0%, bounding a format change at about 28%. Ran on the largest
  available real autoseg series (407 MB, 161,767 traces) plus section-replicated
  derivatives, labeled synthetic. The original lab series were unavailable.
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
  Traces are copied onto every chosen section, including alignment-locked ones.
  A section lock guards its transform/alignment, not its trace content. The
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
- **"What's new" on first launch.** On the first launch of a new version (a
  fresh install or after an update), PyReconstruct shows a dismissible "What's
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
    series. It restarts the application, it does not reload the series. The
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
    another series"). Both rows bring data into the open series: traces,
    z-traces, flags, attributes, alignments, palettes and
    brightness/contrast profiles from another `.jser`, or neuroglancer zarr
    labels converted to objects.
  - `File ▸ Projects` → **Utilities**: the maintainer's catch-all for the
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
  section, which made the lock mean "read-only section", something it already
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
  `Copy <entity> values`. **No action was removed, renamed, or unbound.** All
  112 inventoried actions remain reachable and every keyboard shortcut keeps its
  key (shortcuts are keyed to internal action names, which are unchanged). The
  only label change is `Add to scene` → `Add to 3D scene`, which needs the noun
  now that it sits at top level rather than inside `3D >`.
- **The object menu's "Remove all tags" is filed honestly.** Tags are
  trace-level, so on an object menu this action strips tags from every trace of
  the selected objects, series-wide. That is a bulk trace operation, not an
  object attribute and not geometry (its old home). It now sits in its own
  group above `Delete objects`.
- **The trace list gains `Find > Find in field`**, mirroring what double-clicking
  a row already does, for discoverability.
- **Saved `.jser` files are minified again, so saves are faster and files are
  smaller.** The structural pretty-printing introduced in #102 was kept on the
  assumption it was nearly free. Measured, it was not: on a 391 MB series it cost
  **+11% of save time** and **about 27% more transient memory in the save path**
  (an extra ~411 MB, about one additional copy of the document), for +0.65% of
  file size. Whole-process peak memory was unchanged, which is why the cost went
  unnoticed. Minified is now the default, reversing that part of #102:
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
  still worth it for reading a diff: a one-trace edit on a 781 MB series is 669
  bytes of `diff` output pretty versus the whole file twice minified. The variable
  is now read on **every** write instead of once at start-up, so it can be
  changed in a running session. It replaces `PYRECON_JSER_MINIFY`, which is gone;
  the behavior that variable selected is now the default. Both forms are the
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
  across the object, trace, z-trace, section and flag lists. The copy is
  tab-separated cell values with no header line. The object-menu submenu title
  reverts to "Object attributes" to differentiate it from trace attributes.
  Labels only; `attr_names`, shortcuts, handlers and copy behavior unchanged.
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
  conversion is replaced by `list(starmap(QPoint, pix_pts.tolist()))` (PySide6
  exposes no bulk QPolygon constructor), which is pixel-identical by construction
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
  differs between users. An empty `src_dir` degrades rather than raising (the
  image layer sets `image_found = False` and the window offers to locate the
  images), and the welcome series never used the stored value, since
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
  verified equivalent to the previous implementation: section/object/trace counts
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
  entry carried only the bare event "Mark as needs curation", so *Series ▸
  Restore object curation status from log* had nothing to recover and wrote
  the status back with an empty User column. The event now records the
  assignee ("Mark as needs curation (assigned to `<user>`)") and the restore
  parses it back out. Unassigned markings log the bare event exactly as
  before, and logs written before this change still restore as they did,
  with the status but no assignee, since none was ever recorded in them.
- **The legacy brightness/contrast migration destroyed named profiles.**
  `Section.updateJSON` folds the pre-profiles scalar `brightness`/`contrast`
  pair into `brightness_contrast_profiles`; it did so by *assigning* a fresh
  single-key `{"default": (b, c)}` dict, which discarded every other named
  profile on that section. The exposure was per-open, not one-shot: `saveJser`
  reads each section file out of the hidden directory verbatim (`fast_loads` of
  the raw bytes) rather than through `Section.getDict`, and `updateJSON` left
  the legacy scalars in the dict it wrote, so a section the user never
  individually edited kept its scalars across a save and met the migration
  again on the next open, and the one after that. Only a section that went
  through `Section.save` dropped them, and that save made the loss permanent.
  The migration now **merges**. Whether the legacy pair may become `default` is
  decided by whether the *file* carried a profiles dict at all, captured before
  the back-fill loop inserts the key. It is not decided by comparing values,
  which cannot distinguish a deliberate `(0, 0)` default from the back-filled
  placeholder. No profiles key means a pre-profiles file, whose scalars are its
  only brightness/contrast and become `default`; a profiles dict that is already
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
  legal by `test_jser_canonical_format.py`, and is fail-safe. Honoring a
  stored `False` would *remove* alignment protection on every open. The
  hidden-directory resume path honors the stored value because it resumes a
  live working directory rather than opening a file, so re-locking there would
  discard a lock the user cleared mid-session. Both behaviors are now pinned
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

  **Behavior change, stated plainly: 271 of 271 closed fixture traces change,
  every one of them downward** (old values are always overestimates; 0
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
  the surviving side, or if a log entry records it as deliberately removed. A
  discarded trace always leaves behind both a flag and a log entry. Where the
  machinery cannot decide safely, both sides are kept and the disagreement is
  flagged rather than resolved by picking a winner.

  `Section.importTraces` shortcuts a contour on one Boolean per side from
  `getModifiedSinceDiverge`: *"does this side's log mention this contour after
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
  `keep_below="self"`/`"other"` deleted every unfavored conflict trace overlapping
  a favored one and then cleared the favored pool, so the flagging step had
  nothing left to flag.

  One bound remains, unchanged by this work: when the two logs share no common
  prefix (`last_shared_index == -1`: an empty log, a log trimmed on one side, a
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
  traces (every trace an import between two edited copies actually has to reason
  about), so moving the dialog's "Overlap threshold" slider off its 0.95 default
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
  right-click completion in `lineRelease` to recreate it via `newTrace`, but
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
  data. Only the scissors split its delete from its guarded recreate across two
  event handlers. Upstream issue #51. (#81)
- **An empty object group raised `TypeError` on save.** `getGroupDict` passed a
  bare `set` through unconverted for an empty group, which raises in orjson and in
  the stdlib fallback, so the save died instead of writing. Members are now sorted
  unconditionally. Pre-existing, not introduced by #102. (#103)
- **A non-string object key made the pretty writer emit a file no parser will
  reopen.** `fast_dumps` passes `OPT_NON_STR_KEYS`, so the compact writer coerces
  `1` to `"1"`; dumping a key on its own did not, and the writer emitted a bare
  `1:`. The save succeeded and replaced the previous good file. Keys now go
  through `_dump_key`, which lifts the coercion out of the compact writer rather
  than reimplementing it, so the two cannot drift. Not reachable from the GUI,
  since every keyed map is keyed by a name that is always a string, but the failure
  mode is a silently unreadable file on data that cannot be regenerated. (#103)
- **Trace tags were sorted only when the user happened to touch the section.**
  `Trace.getList` sorts them, but it only runs for a section that goes back through
  the model, while `saveJser` reads the hidden directory verbatim, so identical
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
  `{}` and `""`, so the two output forms disagreed on the key set, the one thing
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
  hands back a real bool. That is the case with the key unset, and for the rest
  of a session after the options dialog writes it, since Qt caches a bool
  in-process and only a fresh process reads the string `"false"` back from the
  INI. A fresh install therefore timestamped in UTC despite
  `default_settings["utc"] = False`.
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
  1.21.0 is the same two channels as 1.20.4. The Developer channel existed
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
[1.21.0-beta-6]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.21.0-beta-5...v1.21.0-beta-6
[1.20.0]: https://github.com/dustenhubbard/PyReconstruct/releases/tag/v1.20.0

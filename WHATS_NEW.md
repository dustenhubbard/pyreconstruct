# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [Unreleased]

## [1.22.0] - 2026-08-21

#### New

- **Search the menus.** Help ▸ Search menus (Cmd+K on macOS, Ctrl+K
  elsewhere) finds any command, including the right-click ones, shows its
  shortcut, and runs it with Enter. Pick a menu-bar result and it opens the
  menus to show you where it lives. The shortcut is remappable like any other.
- **Recolor objects inside the 3D scene.** A new Object Colors submenu changes
  colors without leaving the scene, or reverts them to the series color.
- **Progress bars for bulk section edits.** Setting thickness or
  brightness/contrast across many sections now shows its progress instead of a
  frozen window.

#### Changed

- **"Needs curation" assigns to you, instantly.** No dialog. A new "Needs
  curation (assign to)..." row assigns someone else. The object list now shows
  who assigned each status and when.
- **The What's-new popup is off by default.** Help ▸ Show what's new after
  updates turns it back on; Help ▸ What's new opens the notes any time.
- **Right-click menus follow the classic layout again.** The redesigned menus
  move to the PyReconstruct Dev app. Shortcuts now display beside right-click
  commands on macOS too.
- **Your update channel comes with the app.** The stable app follows stable
  releases; PyReconstruct Dev follows the beta channel. The release channel
  setting in Series Options > Updates has been removed.
- **The "series in use" message says which app has the series open.** With two
  builds installed, "another window" was no longer an answer.

#### Fixed

- **Auto-merge works in point-by-point tracing.** It merges what actually
  overlaps, selected or not, keeps the existing trace's color and tags, and
  one Ctrl+Z removes the drawn trace and its merge together.
- **Tags stay where you put them.** Tagging one trace no longer tags every
  trace edited alongside it, and a refused knife cut no longer brings deleted
  tags back.
- **A crash toggling curation columns from the Lists menu.**
- **The Beta channel offers a stable release when it is the newest build.**
  Beta means earlier access, not a separate lane.

## [1.21.3] — 2026-08-13

- **New: Tired of "What's new" popups? Turn them off.** Click "Don't show
  again", and if you miss the notes later, **Help ▸ Show what's new after
  updates** turns them back on. **Help ▸ What's new** still works any time.
  The window is also a bit roomier, with the extra space going to the notes.
- **Changed: "Reapply autoseg colors" is now "Reapply custom color palette to
  existing objects...", easier to find, and available for the whole series at
  once.** It never was only for autoseg objects: it recolors whatever you
  select using the current palette. It now sits directly in the object
  right-click menu instead of a submenu, and a new **View ▸ Recolor all
  objects from palette** recolors every object in the series in one undoable
  step, skipping locked objects and telling you how many it will touch before
  it does anything.
- **Changed: The "trace crosses itself" message now tells you what to try.**
  Instead of only reporting that the cut could not be made, it points you at
  **Series ▸ Clean up**, which removes the stray traces automatic segmentation
  leaves behind, a common cause of the problem.
- **Fixed: A crash opening the z-trace list after an alignment was renamed or
  deleted.** A z-trace or an object can be set to follow a particular
  alignment, but renaming or deleting that alignment left them pointing at one
  that no longer existed. The z-trace list works out a length for every row as
  it opens, so a single z-trace in that state stopped the whole list from
  opening, and the same problem broke smoothing that z-trace and adding it to
  a 3D scene. Renaming an alignment now carries those settings across, deleting
  one clears them, and anything still pointing at a missing alignment falls
  back to the series alignment instead of failing. A series already in that
  state repairs itself the next time you edit its alignments.
- **Fixed: A crash when using undo or redo after an earlier undo.** When both a
  series-wide undo and an undo for just this section are available, and they
  are not part of the same operation, PyReconstruct compares the two to work
  out which one Ctrl+Z should take. Some saved states were missing the
  timestamp that comparison needs, so undoing and then pressing Ctrl+Z again
  could fail instead of undoing anything.

## [1.21.2] — 2026-08-13

- **Fixed: Picking a color no longer paints the whole picker window that color.** Choosing a color for
  a trace or a flag quietly attached that color to the picker itself, so the next time it opened, the
  entire window came up solid yellow, green, or purple with the controls floating on top of it. The
  picker now opens looking like a normal window, every time, on every platform.
- **Fixed: The attributes window now shows your object's color.** Opening "Set Attributes" on an object
  always left the color swatch blank and opened the picker on white, even when the object had a
  perfectly good color. The swatch now shows the object's color, checked across every section it
  appears on. If its traces do not all agree, wherever the odd ones out live, the swatch splits
  diagonally, the most common color against a blank half, so you can see there is a mix before deciding
  to repaint. And the shown color is just a preview: unless you actually pick a color, pressing OK
  leaves every trace's color exactly as it was.
- **Fixed: A crash while editing an object's attributes with the Object List open.** Renaming an
  object, or making any attribute edit that moves a row, could crash with a "can only join an iterable"
  error while the list was updating. The list now handles the moment an object's row is on its way out,
  whatever columns you have enabled.

## [1.21.1] — 2026-08-07

- **Improved: Every slider in Series ▸ Options shows what it is set to.** The sliders were a bare handle
  on a blank groove, so the only way to learn a setting's value was to close the dialog and watch what
  the program did. **CPU usage** now reads as `50% (5 of 10 workers)`, scale bar size and 3D XY
  resolution read as percentages, and every slider carries tick marks.
- **Changed: The scale bar width setting actually moves the scale bar.** The bar could only be drawn at
  a few set lengths, so most of the 81 positions on the slider drew exactly the same bar; it
  now has many more lengths to choose from, and tick marks divide each one into readable steps. Lengths
  also print one way now, so the same bar no longer reads `10 µm` at one zoom and `10.0 µm` at another.
- **Fixed: A section that fails to load no longer leaves the field stuck and unclosable.** Jumping to a
  section PyReconstruct could not read left the view with nothing to draw, so every redraw raised the
  same error and reopened the error window as fast as you could close it, with Task Manager the only way
  out. A jump that fails now leaves you on the section you were already viewing.
- **Fixed: An error that keeps happening opens one window instead of an endless stream.** An error
  raised while the view redrew came back on every redraw, and each occurrence opened another window on
  top of the last. Each fault now opens a single window per session, and every occurrence is still
  written to the log file, which **Help ▸ View log file** shows.
- **Fixed: On macOS, a color picked for a trace is no longer thrown away.** Clicking a color swatch
  opened the shared system "Colors" panel, where picking a color changed nothing on screen and closing
  the panel discarded the choice, leaving the swatch blank. Swatches now open PyReconstruct's own color
  dialog, the one Windows and Linux already used, with **OK** inside its own window.
- **Fixed: Canceling the flag list's color filter no longer empties the list.** Under
  **Filter ▸ Color filter ▸ Set filter...**, a canceled picker was read as a choice of black, so the
  list hid every flag that was not pure black and "Remove filter" was the only way back. Cancel now
  leaves the filter alone, on every platform.
- **Fixed: The autoseg color editor keeps the color you pick, and opens on the right one.** Add and
  Edit under **Series ▸ Options ▸ View ▸ Autoseg import colors** had the same macOS problem as the trace
  swatch, and the picker opened on white rather than on the color being edited, so pressing OK without
  changing anything wrote white over it.
- **Fixed: Opening Series ▸ Options no longer shrinks the scale bar on its own.** The dialog squeezed
  the stored width into a wider slider range and back again, and that round trip lost a point for most
  values, the shipped default among them, so pressing OK on a dialog nobody had touched made the bar
  narrower every time.
- **Fixed: Reset Defaults moves the sliders in Series ▸ Options.** Three of them, 3D XY resolution,
  scale bar size and CPU usage, read the stored value rather than the shipped default, so they stayed
  exactly where you had left them while the rest of the dialog reset.
- **Fixed: Exporting a section to SVG works again.** Under **File ▸ Export**, saving a section as SVG
  relied on a drawing package that was never actually included, so instead of exporting the feature
  could only prompt you to install it yourself, and on the one-click installers it could not run at
  all. That package now ships with PyReconstruct. (Exporting to PNG needs the same package plus a
  system graphics library; that piece is included too, and the app now tells you what is missing
  instead of failing silently.)

## [1.21.0] — 2026-08-05

- **Changed: In focus mode, editing which object a trace belongs to is now Ctrl-click.** Hold **Ctrl**
  (**Cmd** on macOS) and click to split a trace out of the focused object, or to pull another object's
  trace into it. That was Shift-click; it is now the same key as **Merge traces**, so your hand stays
  where it is between the two halves of a proofreading pass. Shift-click no longer does this edit, and
  being able to remap the modifier yourself is coming.
- **Changed: Right-click menus lead with what you actually do, and say what they act on.** In the field,
  Edit, Merge, Merge attributes only and Hide are one click instead of a level down under "Trace"; on an
  object, Comment, Duplicate object, Hide, Add to 3D scene and Groups are all one click; and every list
  opens with a real action rather than "Invert selection". Commands that appear on both the object and
  the trace menu now name their target, so **Smooth object** (every section) reads differently from
  **Smooth selected traces** (this section's selection). Nothing was removed, nothing moved out of
  reach, and no keyboard shortcut changed.
- **Changed: Imports flag disagreements instead of settling them quietly.** "Check series histories" is
  ticked by default in the import window, so your first import with this version will probably raise
  more flags than you are used to, some of them named "import-removed". Nothing new is wrong: those
  disagreements were always in your data and the import used to pick a side without telling you. Untick
  it for the old behavior; traces that match on both sides still merge silently as before.
- **Changed: Saved series files are written in a compact, repeatable form.** Two saves of an unchanged
  series now produce byte-for-byte identical files, so comparing two copies, or keeping one in version
  control, shows only what you really changed. Files remain fully compatible in both directions, so
  nothing changes about what you can open or who you can share with.
- **Changed: PyReconstruct checks once a day for a new version, and shows release notes once.** The
  daily check was previously off unless you switched it on, and updating turns it on; you can turn it
  off again under **Series ▸ Options ▸ Updates**, where you can also switch to the Beta channel to get
  fixes sooner. Notes now appear once, after an update lands, instead of both when it is offered and
  again on first run. **Help ▸ What's new** reopens them on demand.
- **New: "Clean up" tools tidy stray traces across a series.** **Series ▸ Clean up** removes duplicate
  traces, empty traces, and tiny "pixel-dust" specks below a size in pixels you choose, and a separate
  scan finds similarly shaped traces filed under two *different* names and lets you keep whichever you
  want. You review every list before anything is deleted, each clean-up is one undo step (Ctrl+Z), and
  locked objects are never touched.
- **New: Work on a range of sections, and on just the objects you care about.** "Copy to sections..."
  places selected traces at the same spot across a whole range at once, and an Align by correlation
  shift (`Ctrl+\`) can now be propagated across a range the way a manual transform always could. "Hide
  other objects" isolates your selection across the series, "Restore previous visibility" puts back
  what you had before it, and "Invert selection" flips which objects, or which traces on this section,
  are selected. Two new shortcuts: `Ctrl+Shift+D` adds the selected objects to the 3D scene, and
  `Ctrl+Shift+I` inverts the selection.
- **New: Take an alignment straight from a collaborator's series.** **Alignments ▸ Import alignments** now
  gathers all three sources together with `.jser` first: pick a series, tick the alignments you want,
  and rename any of them on the way in. Importing onto a name you already use asks first and names what
  would be replaced, and the whole import undoes with Ctrl+Z.
- **New: The colors of imported segmentations are yours to choose.** Traces brought in from automatic
  segmentation are colored from a colorblind-friendly palette that also stands out against the
  grayscale image, and **Series ▸ Options** shows that palette as clickable swatches you can change, add
  to, remove from, or reset. "Shuffle colors" re-rolls what you are previewing, the import keeps exactly
  the colors you were shown, and "Reapply autoseg colors" brings earlier imports up to the current
  palette.
- **Improved: Big, dense series feel much faster and use far less memory.** Selecting with the lasso on
  a dense automatic segmentation went from about fourteen seconds to about one in our testing, and a
  densely traced frame redraws over one and a half times faster. Trace measurements are now worked out
  when something asks for them rather than carried around for every trace, which cuts the memory a
  large series spends on its traces by up to about three quarters.
- **Fixed: Several ways your work could quietly disappear are now closed.** Locking an object now stops
  every action that would change its traced data, including one sequence that deleted traces with no
  message at all; renaming an object can no longer leave a series that will not reopen, and this build
  repairs a file already broken that way; deleting a section removes exactly the sections you chose and
  no longer leaves a deleted one to come back on the next save; editing several traces or objects at
  once no longer erases their tags or their comments; and the knife and the scissors no longer destroy a
  trace when a cut cannot be made or the trace layer is hidden. Dragging traces and paging to another
  section before letting go now cancels cleanly and tells you the traces were put back.
- **Also:** several dozen smaller fixes and refinements. Duplicate detection now finds duplicate *open*
  traces, which were previously never reported however closely they lay together. Brightness and
  contrast no longer need a section unlocked, and renaming or deleting a profile is undoable. A trace's
  new color shows immediately everywhere. Undo is safe on Windows for objects whose names carry accents
  or non-Latin characters, and files saved here open correctly in the standard PyReconstruct for your
  collaborators. Converting images to a scaled Zarr no longer takes over your computer, with a **CPU
  usage** slider in **Series ▸ Options** that genuinely controls it and a clearer default location for
  the result. Also fixed: "Merge attributes only", which had failed every time it was used since 2023;
  minimum Feret, now a trace's true narrowest width; the error window's "Copy report to clipboard";
  **Help ▸ View log file**; the searchable user-guide wiki under **Help ▸ Online resources**; a repaint
  loop after undoing an alignment change; filter rows that quietly replaced what you typed; and
  occasional "Save failed" messages on Windows. See the full release notes on GitHub.
- **Worth knowing.** The overlap threshold in the duplicate scans now means something different for
  **open traces**, and exactly what it always meant for closed ones: a closed trace's threshold compares
  enclosed areas, while an open trace encloses nothing, so for open traces it now compares how much of
  each trace's length runs within a few pixels of the other. 0.95 is safe; raise it to be stricter.
  Renaming an object onto the name of one it hosts now drops that host relationship without a prompt,
  since only one object is left. And clearing every tag from a mixed selection, or clearing a comment
  across objects that disagree, can no longer be done in one step from those dialogs, because both were
  only possible through the bugs above.

## [1.20.4] — 2026-07-04

- **Faster first edits on large series.** The first time you recolor or rename an object in a big dataset no longer stalls.
- **Clearer wording when smoothing skips a trace.** The dialog after smoothing now calls them "skipped traces" and shows the reason for each, instead of "malformed contours."
- **"Go to trace" zooms right in.** Jumping to a skipped trace now centers and zooms on that individual trace, the same as double-clicking it in the Trace List.
- **Progress bar while propagating.** Propagating an alignment to the start or end of a series now shows a progress bar instead of the window looking frozen.
- **Progress bar while locking or unlocking sections.** Bulk-locking or unlocking a large set of sections now shows a progress bar.
- **Fixed a crash in Series ▸ Options.** Changing options no longer risks an error on some setups.

## [1.20.3] — 2026-06-29

- **Your palette layout sticks.** Drag the brightness/contrast sliders, increment
  buttons, or scale bar where you want them. They reopen right where you left them.
- **A clearer "What's new."** This dialog now shows your version and release date,
  and sums up everything new since the version you last had.

## [1.20.2] — 2026-06-29

- **A calmer first launch.** PyReconstruct remembers who you are, so it no longer
  pops up a box asking for your name every time it starts.
- **See what changed.** A short summary like this one now appears after you update.
- **The window remembers itself.** PyReconstruct reopens at the size and position
  you left it, and opens a little smaller on a brand-new install.
- **Your palette stays put.** If you hide the section-increment buttons, the
  brightness/contrast sliders, or the scale bar, they stay hidden next time too.

## [1.20.1] — 2026-06-29

- **Much faster with large series.** Opening and working in big datasets is
  dramatically quicker.
- **Easy installers.** One-step installers for Windows, macOS (Apple Silicon and
  Intel), and Linux.
- **Updates from inside the app.** PyReconstruct can now check for and install new
  versions for you. No manual download needed.

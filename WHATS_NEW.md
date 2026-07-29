# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [Unreleased]

## [1.21.0] — 2026-08-04

- **New:** "Clear recents" empties the list of recently opened series. It sits at the bottom of File ▸ Open recent series, below a separator so you cannot hit it by accident.
- **Changed: Menus put what you do at the top, and say what they act on.** Right-click menus now lead with real actions: in the field, Edit, Merge, Merge attributes only and Hide are one click instead of a level down under "Trace"; on an object, Comment, Duplicate object, Hide, Add to 3D scene and Groups are all one click; and every list (objects, traces, z-traces, sections, flags) opens with a real action instead of "Invert selection", which moved down beside "Copy values". In the File and Series menus, items now name their object: "Reload" is "Restart PyReconstruct" (it restarts the whole program and reopens your series), "Open" is "Open series...", "Open recent" is "Open recent series", "Close" is "Close series" (it returns you to the welcome series rather than quitting), "New" is "New series", "Export" is "Export series", "Import" is "Import series data" (with "From another series..." inside it), and "Update curation from history" is "Restore object curation status from log" — it reads your series log and puts back curation statuses the series has lost, now including who a "Needs curation" object was assigned to, without ever clearing a status or undoing an object you marked curated. File ▸ Projects is now File ▸ Utilities — the home for rarely used, special-request tools — and "Randomize images..." there is "Randomize project...", matching "De-randomize project...". Nothing was removed, nothing moved out of reach, and no keyboard shortcut changed.
- **Changed: Imports now flag disagreements instead of settling them quietly.** "Check series histories" is ticked by default in the import window, so your first import with this version will probably raise more flags than you are used to, some of them named "import-removed" — untick it if you want the old behaviour. Nothing new is wrong: those disagreements were always in your data, the import used to pick a side without telling you, and traces that match on both sides still merge silently as before.
- **Changed: Saved series files are written in a compact, repeatable form.** Two saves of an unchanged series now produce byte-for-byte identical files, so comparing two copies — or keeping one in version control — shows only what you really changed. A `.jser` is still one long line if you open it in a text editor, and files remain fully compatible in both directions, so nothing changes about what you can open or who you can share with.
- **New: "Clean up" tools tidy stray traces in your series.** Series ▸ Clean up can remove duplicate traces, empty traces, and tiny "pixel-dust" specks below a size in pixels you choose — you review the list before anything is deleted. Every clean-up is one undo step (Ctrl+Z), and locked objects are never touched.
- **New: Apply your work across a range of sections in one step.** Select traces and choose "Copy to sections..." to place them at the same spot on a whole range at once — and the message afterwards names the section numbers that really received them, so anything skipped is visible instead of hidden inside a total. An Align by correlation shift (`Ctrl+\`) can now be propagated across a range too, the way a manual transform always could.
- **New: The colors of imported segmentations are yours to choose.** Traces brought in from automatic segmentation are colored from a colorblind-friendly palette that also stands out against the grayscale image, and Series ▸ Options now shows that palette as clickable swatches you can change, add to, remove from, or reset to the default. A "Shuffle colors" button beside "Import Contours" re-rolls the colors you are previewing, the import keeps exactly the colors you were shown, and "Reapply autoseg colors" in the object right-click menu brings objects you imported earlier up to the current palette.
- **New: Isolate the objects you are working on.** "Hide other objects" hides everything except your selection across the whole series, so an object stays isolated as you page through sections; "Show all objects" brings them back, and "Hide all objects" clears the view so you can reveal objects a few at a time. "Invert selection" flips which objects — or which traces on the current section — are selected, so you can pick a few and instantly switch to all the rest. Look in the object list's Selection menu or its right-click menu.
- **New: You decide when the 3D scene updates itself.** Edits to your 2D traces now show up in an open 3D view right away instead of leaving a stale object there until you reload it — and if you would rather it waited while you make many edits on a large series, you can turn auto-refresh off from the 3D window's Scene menu or in Series ▸ Options. "Refresh edited objects" (Ctrl+R) still works anytime, and switching auto-refresh back on catches the scene up immediately.
- **Improved: Big, dense series feel much faster and use far less memory.** Selecting with the lasso on a dense automatic segmentation went from about fourteen seconds to about one in our testing, and a densely traced frame redraws over one and a half times faster. Trace measurements are now worked out when something asks for them, instead of being carried around for every trace, which cuts the memory a large series spends on its traces by up to about three quarters.
- **Improved: Converting images to a scaled Zarr no longer takes over your computer.** The conversion no longer grabs every CPU core, so your laptop stays usable while it runs, and the "CPU usage" slider in Series ▸ Options now genuinely controls how much of your processor it uses — with tick marks, a short explanation, and a default of about half your cores. It also suggests a clearer place for the result: a `<series>.zarr` folder right next to your images.
- **Fixed: Several ways your work could quietly disappear are now closed.** Importing one copy of a series into another could drop a trace with no flag and no log entry — sometimes your own — and the import window's "Overlap threshold" slider was ignored on exactly the traces it mattered for; both are fixed, and where two copies genuinely disagree both traces are now kept and flagged instead of one being chosen silently. The scissors tool no longer destroys a trace when the trace layer is hidden, undo no longer risks an object's traces on Windows when its name contains accents or non-Latin characters, and opening a series no longer discards brightness/contrast profiles you had named.
- **Also:** a couple of dozen smaller fixes and refinements. Brightness and contrast no longer need a section unlocked; the error window can copy a full problem report to your clipboard; Help ▸ View log file shows messages that used to appear only in a console; Help ▸ What's new reopens these notes on demand; the user guide is now a searchable wiki under Help ▸ Online resources; and the update channels in Series ▸ Options ▸ Updates are now named Stable and Beta. Also fixed: minimum Feret is now a trace's true narrowest width rather than a corner-to-corner distance, occasional "Save failed" hiccups on Windows, the main window opening tiny after a change of monitor, saving a series that has an empty object group, and files saved here opening correctly in the standard PyReconstruct for your collaborators — see the full release notes on GitHub.

## [1.20.5rc1] — 2026-07-04

- **Your work is better protected.** Fixed several cases where edits could be lost or a file corrupted, including edits made just before flickering between sections, and saves interrupted by a crash or a full disk.
- **Safer handling of shared files.** Hardened how PyReconstruct opens and converts series files received from others.
- **Align by correlation fixed.** It now applies the correlation shift correctly even when the section is rotated or scaled.
- **Smoother on large, dense series.** The trace under your cursor highlights without lag, the field redraws faster as you pan and zoom, and background jobs like exports and update checks run more reliably.

## [1.20.4] — 2026-07-04

- **Faster first edits on large series.** The first time you recolor or rename an object in a big dataset no longer stalls.
- **Clearer wording when smoothing skips a trace.** The dialog after smoothing now calls them "skipped traces" and shows the reason for each, instead of "malformed contours."
- **"Go to trace" zooms right in.** Jumping to a skipped trace now centers and zooms on that individual trace, the same as double-clicking it in the Trace List.
- **Progress bar while propagating.** Propagating an alignment to the start or end of a series now shows a progress bar instead of the window looking frozen.
- **Progress bar while locking or unlocking sections.** Bulk-locking or unlocking a large set of sections now shows a progress bar.
- **Fixed a crash in Series ▸ Options.** Changing options no longer risks an error on some setups.

## [1.20.3] — 2026-06-29

- **Your palette layout sticks.** Drag the brightness/contrast sliders, increment
  buttons, or scale bar where you want them — they reopen right where you left them.
- **A clearer "What's new."** This dialog now shows your version and release date,
  and sums up everything new since the version you last had.

## [1.20.2] — 2026-06-29

- **A calmer first launch.** PyReconstruct no longer pops up a box asking for your
  name every time it starts — it remembers who you are.
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
  versions for you — no manual download needed.

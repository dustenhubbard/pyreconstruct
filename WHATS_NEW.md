# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [Unreleased]

## [1.21.0-beta-7] — 2026-07-31

- **Fixed: A deleted section no longer comes back the next time you open the series.** Deleting a section,
  saving and reopening could bring it back, with its z-trace point gone and the log recording a deletion
  that did not stick. Nothing reported an error. Deleting the highest-numbered section instead failed the
  save outright, left the progress dialog stuck, and made every save after it fail too. The writer built its
  list of sections from the files it found on disk rather than from the series, so a section the series had
  removed was written back out.
- **Fixed: Duplicate detection finds duplicate open traces.** Open traces were compared by the area they
  enclose, and an open trace does not enclose an area, so duplicates went unreported however closely the two
  lay on top of each other. Open traces are now compared along their length instead. Closed traces are
  unchanged in how they are measured. Reported by Lyndsey Kirk.
- **Fixed: The knife no longer deletes the object when the cut cannot be made.** A cut it could not compute
  removed the trace instead of leaving it alone.
- **Fixed: Dragging traces and paging to another section before letting go no longer looks like it deleted
  them.** A drag hides the traces it is carrying and draws them under the cursor, and only the release puts
  them back. Since the wheel pages sections with the button still held, releasing on a different section put
  nothing back anywhere: the traces stayed hidden on the section they came from, invisible and unclickable
  when you paged back to it. The gesture now cancels cleanly and tells you the traces were put back.
  Dragging traces *onto* another section is currently being worked on.
- **Fixed: The 2D field selects a locked object's traces again.** Locking an object stopped its traces from
  being selectable in the field. Locking refuses changes to quantitative trace data, never selection, color,
  or visibility.
- **Fixed: Splitting an object no longer leaves a stray "last edited by" record under its old name.**
  "Split into separate objects" gives each of the object's traces its own numbered name, so the object you
  started from is left with nothing on any section. Everything attached to it is cleared correctly, but the
  log written straight afterwards put the editor stamp back, on an object that no longer existed. It was
  saved into the series, so any new object later given that name inherited it.
- **Fixed: Renaming and deleting brightness/contrast profiles behave.** Both rewrote the profile on every
  section without recording an undo state, so Ctrl+Z could not reach either one, and renaming the profile
  you were looking at dropped the display back to the default until you switched away and back.
- **Fixed: Importing transforms adds the new alignment to the alignment menu immediately.** The alignment
  was imported, but did not appear in the menu until something else happened to rebuild it.
- **New: `Alignments ▸ Import alignments ▸ From another series (.jser)`.** Taking an alignment from a
  colleague's series was reachable only through `Series ▸ Import series data`, the whole-series merge dialog
  where alignments are one tab among eight. All three sources now sit together, with `.jser` first as the
  common case: pick a series, tick the alignments you want, and rename any of them on the way in. Importing
  onto a name your series already uses now asks and names what would be replaced, rather than refusing
  outright, and the whole import can be undone with Ctrl+Z.
- **New: `Series ▸ Clean up ▸ Find duplicates named differently...`** finds similarly shaped and positioned
  traces under two different names, and lets you remove whichever one you do not want. The existing "Remove
  duplicate traces..." only compares traces that share the same name, so it never sees these. Each pair is
  listed with both names, the measured overlap and both areas, and you can jump to either in the field. Tick
  the name to keep, and "Delete unselected" removes the other; rows you leave alone are untouched. It never
  guesses which name is right, because that is a judgment about your data rather than about the geometry. A
  batch of deletions can be undone with one Ctrl+Z, and locked objects are left alone.
- **New: `Restore previous visibility`** puts back the visibility you had before "Hide other objects", on
  the object right-click menu directly beneath it. Previously the only way back was "Show all objects",
  which unhides everything and throws away any hiding you had done deliberately.
- **New: Ctrl+Shift+D adds the selected objects to the 3D scene.** The action had no shortcut and no row in
  the shortcuts dialog to assign one; it now has both and is remappable to another shortcut if you prefer.
- **New: Ctrl+Shift+I inverts the selection.** The action existed with a right-click row and a working
  handler, but its shortcut was written into the source as an empty string, so it had no key and no row in
  the shortcuts dialog. The selection trio now reads Ctrl+A, Ctrl+D, Ctrl+Shift+I, and all three are
  remappable.
- **Changed: Five right-click commands that appear on both the object and the trace menu now say what they
  act on.** `Smooth object` against `Smooth selected traces`, and the same pairing for hide, unhide, edit
  radius and edit shape. The labels were identical while the commands were not: the object version works on
  every section the object appears on, the trace version on the current selection on the current section,
  and now the labels say which.
- **Changed: The object right-click menu is reordered** so `Add to 3D scene` sits next to the `3D ▸`
  submenu, and the per-object settings are collected in one place. Nothing was renamed, added or removed,
  and the visibility family is untouched.
- **Changed: The log now says when an alignment import replaced an existing alignment**, instead of
  recording every import the same way. If you want to keep the old alignment as well, give the incoming one a
  different name in the import dialog: each row's target name is yours to edit, and only a name already in
  use asks you to confirm a replacement. Ctrl+Z restores an alignment if you replace one by accident.
- **Worth knowing.** The overlap threshold in the duplicate scans now means something different for **open
  traces**, and exactly what it always meant for **closed traces**. For a closed trace the threshold
  compares enclosed areas, and still does. An open trace encloses nothing, which is why the old measure
  missed obvious duplicates; for open traces the threshold now compares how much of each trace's length
  runs within a few pixels of the other. 0.95 is safe. Raise it if you want the scan to be stricter.

## [1.21.0-beta-6] — 2026-07-30

- **Fixed: Locking an object now protects it everywhere.** Locking is meant to stop anything that would change your traced data, but several actions went around it: cutting (Ctrl+X), pasting attributes (Ctrl+B), nudging with the arrow keys, the scalpel, dragging a selected trace, and splitting a trace in focus mode all worked on a locked object's traces. One sequence deleted them with no message at all: select a trace, turn on focus mode, tick Locked on that object in the object list, move to the next section, then cut. Undo would have brought them back, but nothing told you there was anything to undo. All six actions now refuse and say so.
- **Fixed: Renaming an object could produce a series that would no longer open.** If you renamed an object to the name of something it hosts, the rename stopped partway with an error, leaving both names in the series, and PyReconstruct kept running. Saving from that point wrote a file that failed to open afterwards. The rename now completes properly, and this build also repairs a series already broken this way when it opens it, so a file you could not open before should open now.
- **Fixed: Deleting a section could leave a series in a broken state, with no way back.** Selecting a section in the list and deleting it removed the file and then stopped partway through, because the section was passed to the delete once for every column in the list rather than once. The section list no longer matched what was on disk, and every z-trace kept a point on the section that no longer existed, which was written back out on the next save. Deleting now removes exactly the sections you selected, and reports any problem before removing anything.
- **Fixed: Editing several traces at once no longer erases their tags.** If the traces you selected did not all carry the same tags, the Tags field showed empty, and clicking OK cleared the tags on every one of them. Nothing indicated it. Leaving that field alone now leaves each trace's own tags alone. If you want to clear tags across a mixed selection, the object list's "Remove all trace tags" still does it.
- **Fixed: "Delete duplicate traces" no longer stops with an error on some series.** Two traces lying along the same straight line made the scan fail partway through, so the clean-up stopped where it was and sections after that point were never scanned. Nothing was lost, but nothing was cleaned up either. Reported by Lyndsey Kirk.
- **Fixed: The object attributes dialog can finally remove a tag.** It showed an object's tags, let you delete one, and then discarded the change without saying anything. Removing a tag now works when a single object is selected. With several selected the dialog still only adds, because it cannot show you what the selection really has.
- **Fixed: Editing a comment on several objects at once no longer erases it.** The comment box was blanked whenever more than one object was selected, even when they all had the same comment, and that blank was then written to all of them. The box now fills in when the selection agrees, and leaving it empty on a disagreeing selection writes nothing.
- **Fixed: "Merge attributes only" now works.** It has failed with an error every time it was used, in both places it appears, since 2023.
- **Fixed: Leaving the opacity box empty in the 3D object settings no longer breaks the opacity keys.** It stored an empty value, after which the `]` and `[` keys raised an error instead of changing opacity, and a saved scene recorded the empty value too. Leaving the box blank now leaves opacity as it was.
- **Fixed: PyReconstruct no longer becomes unusable after undoing an alignment change.** Undoing the creation of an alignment left its name in the field's "Series alignment" menu, and choosing it put the window into a repaint loop that could only be ended by force-quitting. The menu is now rebuilt when an undo changes which alignments exist.
- **Fixed: Typing a filter into an added row now filters on what you typed.** In five places, the "Add to scene" dialog's object and z-trace filters and the import dialog's trace and z-trace filters, a row added with the "+" button quietly replaced what you typed with a real object's name, and the import or the scene addition then acted on that object instead. The first row in each field was never affected, which is why this was easy to miss.
- **Fixed: Editing tags in the trace palette no longer creates an empty tag.** Deleting one tag from a list left a trailing separator behind, which was stored as a tag with no name and then offered in the tag filters.
- **Improved: The "+" and "−" buttons in filter and tag fields behave sensibly.** "−" now removes the row your cursor is in rather than always the last one, so correcting the first of several entries no longer means deleting everything below it. On the last remaining row it clears the text instead of leaving you with nothing to type into. The dialog also gives back its height on the press that removes a row, rather than a row later. Tags now appear in a consistent order instead of moving between rows each time a dialog opens.
- **Changed: Hiding a locked object's traces is no longer refused.** Locking guards your data, not what you can see. This was only reachable through focus mode, so most people will not have met it.
- **Changed: Release notes are shown once, after an update lands, rather than twice.** They used to appear when an update was offered and again the first time the new version opened. The update prompt now links to the notes instead of repeating them.
- **Fixed: The manual was wrong about undo.** It said twice that Ctrl+Z would not undo anything done through the object or section list. It does, across the whole series, and it asks whether to undo everywhere or only on the current section when a change spanned several. The manual also said editing an object's attributes and editing a stamp's radius could not be undone. Both can, and have been able to for some time.
- **Security: Bundled dependencies are updated to clear twelve published advisories.** None of them was reachable from PyReconstruct, so nobody was exposed. This keeps the versions defensible to a scanner rather than responding to anything.
- **New:** "Clear recents" empties the list of recently opened series. It sits at the bottom of File ▸ Open recent series, below a separator so you cannot hit it by accident.
- **Changed: Menus put what you do at the top, and say what they act on.** Right-click menus now lead with real actions: in the field, Edit, Merge, Merge attributes only and Hide are one click instead of a level down under "Trace"; on an object, Comment, Duplicate object, Hide, Add to 3D scene and Groups are all one click; and every list (objects, traces, z-traces, sections, flags) opens with a real action instead of "Invert selection", which moved down beside "Copy values". In the File and Series menus, items now name their object: "Reload" is "Restart PyReconstruct" (it restarts the whole program and reopens your series), "Open" is "Open series...", "Open recent" is "Open recent series", "Close" is "Close series" (it returns you to the welcome series rather than quitting), "New" is "New series", "Export" is "Export series", "Import" is "Import series data" (with "From another series..." inside it), and "Update curation from history" is "Restore object curation status from log" (it reads your series log and puts back curation statuses the series has lost, now including who a "Needs curation" object was assigned to, without ever clearing a status or undoing an object you marked curated). File ▸ Projects is now File ▸ Utilities, the home for rarely used, special-request tools. "Randomize images..." there is "Randomize project...", matching "De-randomize project...". Nothing was removed, nothing moved out of reach, and no keyboard shortcut changed. The rarely used tools under File ▸ Utilities now explain themselves on hover, including that randomizing a project writes a decode.txt key file you must keep to get your original image names back. And the keyboard shortcut shown at the right of a menu item now keeps clear space from even the longest label instead of crowding it.
- **Changed: PyReconstruct now checks once a day for a new version and tells you when one is out.** This was previously off unless you switched it on, and updating turns it on once. You can turn it off again under Series ▸ Options, where you can also switch to the Beta channel to get fixes and new features sooner.
- **Worth knowing.** Renaming an object onto the name of one it hosts now drops that host relationship, without a prompt, since only one object is left. Clearing every tag from a mixed selection, or clearing a comment across objects that disagree, can no longer be done in one step from those dialogs; both were only possible because of the bugs above. And importing an alignment from a `.txt` file still does not add it to the alignment menu until something else rebuilds it.

## [1.21.0-beta-5] - 2026-07-28

- **Your work is better protected.** Fixed several cases where edits could be lost or a file corrupted, including edits made just before flickering between sections, and saves interrupted by a crash or a full disk.
- **Safer handling of shared files.** Hardened how PyReconstruct opens and converts series files received from others.
- **Smoother on large, dense series.** The trace under your cursor highlights without lag, the field redraws faster as you pan and zoom, and background jobs like exports and update checks run more reliably.
- **Changed: Imports now flag disagreements instead of settling them quietly.** "Check series histories" is ticked by default in the import window, so your first import with this version will probably raise more flags than you are used to, some of them named "import-removed". Untick it if you want the old behavior. Nothing new is wrong: those disagreements were always in your data, the import used to pick a side without telling you, and traces that match on both sides still merge silently as before.
- **Changed: Saved series files are written in a compact, repeatable form.** Two saves of an unchanged series now produce byte-for-byte identical files, so comparing two copies, or keeping one in version control, shows only what you really changed. A `.jser` is still one long line if you open it in a text editor, and files remain fully compatible in both directions, so nothing changes about what you can open or who you can share with.
- **New: "Clean up" tools tidy stray traces in your series.** Series ▸ Clean up can remove duplicate traces, empty traces, and tiny "pixel-dust" specks below a size in pixels you choose. You review the list before anything is deleted. Every clean-up is one undo step (Ctrl+Z), and locked objects are never touched.
- **New: Apply your work across a range of sections in one step.** Select traces and choose "Copy to sections..." to place them at the same spot on a whole range at once. The message afterwards names the section numbers that really received them, so anything skipped is visible instead of hidden inside a total. An Align by correlation shift (`Ctrl+\`) can now be propagated across a range too, the way a manual transform always could.
- **New: The colors of imported segmentations are yours to choose.** Traces brought in from automatic segmentation are colored from a colorblind-friendly palette that also stands out against the grayscale image, and Series ▸ Options now shows that palette as clickable swatches you can change, add to, remove from, or reset to the default. A "Shuffle colors" button beside "Import Contours" re-rolls the colors you are previewing, the import keeps exactly the colors you were shown, and "Reapply autoseg colors" in the object right-click menu brings objects you imported earlier up to the current palette.
- **New: Isolate the objects you are working on.** "Hide other objects" hides everything except your selection across the whole series, so an object stays isolated as you page through sections; "Show all objects" brings them back, and "Hide all objects" clears the view so you can reveal objects a few at a time. "Invert selection" flips which objects (or which traces on the current section) are selected, so you can pick a few and instantly switch to all the rest. Look in the object list's Selection menu or its right-click menu.
- **New: You decide when the 3D scene updates itself.** Edits to your 2D traces now show up in an open 3D view right away instead of leaving a stale object there until you reload it. If you would rather it waited while you make many edits on a large series, you can turn auto-refresh off from the 3D window's Scene menu or in Series ▸ Options. "Refresh edited objects" (Ctrl+R) still works anytime, and switching auto-refresh back on catches the scene up immediately.
- **Improved: Big, dense series feel much faster and use far less memory.** Selecting with the lasso on a dense automatic segmentation went from about fourteen seconds to about one in our testing, and a densely traced frame redraws over one and a half times faster. Trace measurements are now worked out when something asks for them, instead of being carried around for every trace, which cuts the memory a large series spends on its traces by up to about three quarters.
- **Improved: Converting images to a scaled Zarr no longer takes over your computer.** The conversion no longer grabs every CPU core, so your laptop stays usable while it runs, and the "CPU usage" slider in Series ▸ Options now genuinely controls how much of your processor it uses. The slider has tick marks, a short explanation, and a default of about half your cores. It also suggests a clearer place for the result: a `<series>.zarr` folder right next to your images.
- **Fixed: Several ways your work could quietly disappear are now closed.** Importing one copy of a series into another could drop a trace with no flag and no log entry (sometimes your own), and the import window's "Overlap threshold" slider was ignored on exactly the traces it mattered for; both are fixed, and where two copies genuinely disagree both traces are now kept and flagged instead of one being chosen silently. The scissors tool no longer destroys a trace when the trace layer is hidden, undo no longer risks an object's traces on Windows when its name contains accents or non-Latin characters, and opening a series no longer discards brightness/contrast profiles you had named.
- **Also:** a couple of dozen smaller fixes and refinements. Brightness and contrast no longer need a section unlocked; the error window can copy a full problem report to your clipboard; Help ▸ View log file shows messages that used to appear only in a console; Help ▸ What's new reopens these notes on demand; the user guide is now a searchable wiki under Help ▸ Online resources; and the update channels in Series ▸ Options ▸ Updates are now named Stable and Beta. Also fixed: minimum Feret is now a trace's true narrowest width rather than a corner-to-corner distance, occasional "Save failed" hiccups on Windows, the main window opening tiny after a change of monitor, saving a series that has an empty object group, and files saved here opening correctly in the standard PyReconstruct for your collaborators. See the full release notes on GitHub.

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

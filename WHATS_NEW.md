# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [Unreleased]

## [1.23.0-beta-3] — 2026-08-26

#### New

- **Hide the lists with one click.** A sidebar button in the bottom status bar,
  View ▸ Show/hide lists, or Cmd+Option+S (Ctrl+Alt+S on Windows and Linux)
  collapses the whole list area. The same toggle brings back exactly the lists
  you had open, tabs intact. Floating lists stay where they are.
- **PyReconstruct remembers your list layout, per series.** Close a series with
  lists open, docked, tabbed, floating, or collapsed, and opening it brings the
  same lists back where they were, tiny floating ones included.
- **Right-click the scale bar, the section increment buttons, the
  brightness/contrast sliders, or the trace palette to hide them.** The View
  menu keeps every toggle, and its checkmarks always match, whichever road you
  use.
- **Series ▸ Clean up can repair self-crossing traces.** Autoseg sometimes
  leaves a tiny spike that crosses the outline and blocks the scalpel; the new
  clean-up removes the artifact and keeps the trace's real shape, in one undo.
  A true figure 8 with two real loops is skipped and listed in a review window
  that jumps you to each one for the scissors, and every repair pass ends in a
  summary you can copy or save. Thanks Patrick for reporting this!
- **Choose what the hover shows.** Hover over a trace and the pop-up shows
  object data; a new option under Series ▸ Options picks which columns appear
  and in what order, per series. Ported from Michael's upstream work.
- **The alignment and B/C profile buttons can create.** Each button's menu ends
  with a row that opens the matching edit dialog.

#### Changed

- **List tabs have close buttons, and the double title bar is gone.** The tab
  names the list and its X closes it. A list docked alone keeps its title bar
  so it can still be dragged out.
- **The Help menu is reorganized into five groups:** search (with the cursor
  ready the moment Help opens), the version, updates and the other build's
  download, the What's New pop-up controls, then everything else. Two rows read
  plainer: "Automatically check for updates" and "Turn off What's new pop-up",
  where a tick means off.

#### Fixed

- **Floating lists can be tiny again on purpose.** A floated list sized by hand
  can shrink to a few rows; only lists spawning tiny stay blocked. Thanks
  Patrick for reporting this!
- **The "trace crosses itself" message now gives the right advice for figure
  8s:** cut out the crossing with the scissors tool. Thanks Patrick for
  reporting this!
- **PyReconstruct Dev now starts with your settings.** The first launch of a Dev
  install copies the choices your stable app already holds, once, instead of
  starting from defaults. Thanks Patrick for reporting this!
- **Resizing no longer zooms the view out.** Collapsing the lists or resizing
  the main window nudged the zoom outward a little each time; the view now
  holds its magnification exactly.
- **Docked lists now scroll all the way to the bottom.** A sizing bug could
  hide the last row or two of a docked list, and undocking was the only
  workaround.
- **Switching themes no longer crowds the lists.** Columns re-measure for the
  new theme's font and padding.
- **Prompts name your platform's undo keys.** On macOS they say Cmd+Z, not
  Ctrl+Z.

## [1.23.0-beta-2] — 2026-08-25

#### New

- **Double-click a `.jser` file to open it in PyReconstruct.** The command line
  also takes a jser path directly: `pyreconstruct series.jser`.
- **Find any menu command by typing its name.** Help ▸ Search menus (Cmd+K on
  macOS, Ctrl+K on Windows and Linux) shows where it lives and its shortcut,
  and runs it with Enter.
- **The bottom status bar now has clickable buttons.** Section, alignment, and
  B/C profile open their menus where you clicked.
- **Object colors can be changed inside the 3D scene, independently of the
  object's attributes.**
- **Bulk section edits show a progress bar.**
- **Smoothing has a keyboard shortcut.**
- **The window opens at 70% of the screen,** and View ▸ Reset window puts it
  back there any time.
- **The What's New popup grew up.** It shows the last three releases, links to
  every version's notes on GitHub, and has a "Don't show again" button with a
  Help-menu toggle to turn it back on.
- **Download the other build from the Help menu.** The Dev app links to the
  newest stable release, and the stable app links to the newest Dev beta.
- **PyReconstruct Dev installs beside stable.** Its own app, install location,
  and updates, so testing a beta never touches your stable install.

#### Changed

- **Eight default shortcuts changed** so common actions stop colliding. Every
  one is remappable, and Help ▸ Shortcuts list shows the current keys.
- **The right-click menus follow the stable app's organization, for now.**
- **Recoloring objects from the palette is easier to find,** is no longer
  labeled autoseg-only, and can run over the whole series.
- **Marking an object as needing curation no longer asks anything.** A separate
  row assigns someone else.
- **A checkable menu item no longer closes its menu,** so a set of toggles can
  be set in one trip.
- **The "this series has multiple alignments" popup is gone.**
- **Clearer messages.** The knife's "trace crosses itself" refusal says what to
  try, "series in use" names the app holding the series, and an import that
  cannot use the history check says so before it runs.
- **Smaller installers.** About 13 MB less to download on macOS and Windows,
  nothing removed.
- **The CPU usage slider stops at the worker count that is actually fastest.**

#### Fixed

- **Lists no longer spawn or float tiny.** New lists open as tabs on the
  existing list, and a list dragged out gets a usable size.
- **Tagging one trace no longer tags every trace edited alongside it.**
- **Auto-merge works the same in polygon mode as in pencil mode,** and one undo
  fully reverts an auto-merged trace.
- **Keyboard shortcuts now appear in the right-click menus on macOS.**
- **Cmd+A, Cmd+D and Cmd+Shift+I act on whichever list has focus** instead of
  always acting on the field (Ctrl on Windows and Linux).
- **Cmd+Shift+H now runs Set hosts...,** which it never did from a fresh
  install (Ctrl+Shift+H on Windows and Linux).
- **Rebinding Home now sticks** instead of reverting on the next series open.
- **The z-trace commands are no longer greyed out almost all the time,** and
  the z-trace list no longer crashes after an alignment was renamed or deleted.
- **Fixed crashes:** smoothing a trace on macOS 12, toggling curation columns
  from the Lists menu, undo after an earlier undo, and opening a section with
  an empty contour name.
- **The Beta update channel offers a stable release when it is the newest one.**
- **Settings behave.** A never-saved setting can no longer overwrite the
  shipped default for every series, editing a column list no longer corrupts
  the stored value, a malformed column setting says which one it is, and Reset
  Defaults now resets everything it claims to.
- **Flags keep their identity.** Flags from before flags had IDs stay the same
  on every open, so importing another user's copy merges instead of
  duplicating. The resolved-flags filter turns back off and shows its
  checkmark, and hidden flags and traces are released from memory.
- **Opening a series whose object names contain a space or a comma no longer
  loses those objects' groups, comments, curation status, and host links.**
- **Confirming "Edit alignment..." without touching it no longer clears the
  selected objects' alignment.**
- **"Duplicate object" and "Split into separate objects" no longer write into
  a locked object,** and the scissors tool no longer asks "unlock it?" only to
  ignore the answer.
- **Series history is sturdier.** A damaged row in the edit log no longer takes
  good rows, or an editor's entry, down with it.
- **An opacity of 0 in the 3D scene is no longer discarded.**

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

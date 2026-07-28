# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [Unreleased]

## [1.21.0-beta-5] — 2026-07-28

- **New:** "Clean up" tools tidy stray traces in your series. Under the Series menu, a new "Clean up" submenu can remove duplicate traces, find tiny "pixel-dust" specks below a size in pixels you choose (shown in a list you review and trim before anything is deleted, with each speck's pixel and physical area), and remove empty traces that hold no real shape. Every clean-up is a single step you can undo (Ctrl+Z), and locked objects are left untouched.
- **New:** Choose your own colors for traces imported from automatic segmentation. Series ▸ Options now shows the color palette as clickable swatches: click one to change it, and add, remove or reset the whole set back to the colorblind-friendly default. There is also a "Shuffle colors" button right beside "Import Contours" on the import overlay, so a single click re-rolls the colors you are previewing, and the import keeps exactly the colors you were shown.
- **New:** Recolor segmentations you imported earlier. Objects brought in before these color features kept whatever colors they were given at the time, so they never picked up the friendlier palette. "Reapply autoseg colors" in the object right-click menu pushes the current palette onto the objects you select, in one step you can undo (Ctrl+Z). It asks before replacing colors, and locked objects are left alone.
- **Changed:** Right-click menus put the things you actually do at the top. Every right-click menu now follows the same shape: what you almost always came for is at the top (with its keyboard shortcut shown), the rarer things stay tucked in submenus you already know, and Delete is always last. Right-clicking in the field now offers Edit, Merge, Merge attributes only and Hide straight away instead of one level down under "Trace". On an object, Comment, Duplicate object, Hide, Add to 3D scene and Groups are all one click now. And every list (objects, traces, z-traces, sections, flags) opens with a real action instead of "Invert selection", which has moved down next to "Copy values" where it is the same in all five. Nothing was removed and no keyboard shortcut changed — things just moved closer to hand. New in the trace list: Find ▸ Find in field, which jumps to the trace (the same thing double-clicking a row has always done).
- **Changed:** Imports now flag disagreements instead of settling them quietly. The "Check series histories" option is on by default, so your first import with this build will probably show more flags than you are used to, some of them named "import-removed". Nothing new is wrong: those disagreements were always in your data, and the import used to pick a side without telling you. Traces that match on both sides still merge silently, as before.
- **Improved:** Lasso selection and drawing are much faster on dense series. Selecting with the lasso on a dense automatic segmentation went from about fourteen seconds to about one in our testing, and redrawing a densely traced frame is over one and a half times faster.
- **Improved:** Large series hold far less memory. Trace measurements are now worked out when something asks for them, instead of being carried around for every trace — which cuts the memory a large series uses for its traces by up to about three quarters.
- **Improved:** Saving is faster and saved files are a little smaller. On a large series, saving is about 10% quicker and uses noticeably less memory while it runs. Files stay fully compatible in both directions, so this changes nothing about what you can open or who you can share with.
- **Improved:** Copying traces to other sections now tells you which sections actually received them. The message used to report only a count of the sections you asked for; it now lists the section numbers that were really written to (collapsing long runs, as in "2-5, 10"), so anything that got skipped is visible rather than hidden inside a total.
- **Fixed:** Merging two copies of a series can no longer discard your tracing without telling you. When two people trace the same series in parallel and one copy is imported into the other, the import could drop a trace and leave no record of it — no flag, no log entry — and sometimes the trace it dropped was yours. Now anything discarded leaves both a flag and a log entry, and where the merge cannot tell which side is right it keeps both traces and flags the disagreement instead of picking a winner.
- **Fixed:** The "Overlap threshold" slider in the import window now actually applies. It was ignored on exactly the traces it matters for — the ones that differ between the two copies — where a fixed setting was always used instead. Setting it stricter could even make the import drop your own version of a trace.
- **Fixed:** The scissors tool no longer destroys a trace when the trace layer is hidden. Picking a trace up with the scissors and then finishing with a right-click, while the trace layer was hidden, deleted the trace and put nothing back — that work was simply gone. If the replacement cannot be created, the original trace is now put back.
- **Fixed:** Minimum Feret was being measured the wrong way. It was reported as a distance between two opposite corners of a trace's outline rather than the trace's true narrowest width, so the number came out slightly too high — most noticeably on long, thin shapes such as spine necks. Maximum Feret was correct all along and has not changed.
- **Fixed:** Exporting an object mesh no longer offers a format that cannot work. The Collada (.dae) export needs an extra component that the installers do not include, and picking it simply failed. That menu item is now greyed out and labelled "(not installed)" when the component is missing, so you can see the situation instead of running into it. The other mesh formats are unaffected.
- **Fixed:** Turning off "use UTC time" now works without restarting. Switching the setting off had no effect until PyReconstruct was restarted, and a brand-new installation stamped times in UTC even though the setting was supposed to be off to begin with. Both are sorted out.
- **Fixed:** Saving no longer fails on a series that has an empty object group. If you created an object group and left nothing in it, saving that series failed outright. It now saves normally.
- **Fixed:** Copying objects no longer risks an error when the Feret columns are switched on. With those columns showing in the object list, an ordinary copy of an object could stop with an error; a value that is not available yet now simply shows as blank and fills in when you change sections.
- **Removed:** The "Developer" update channel is gone. Updates now come on two channels, Stable and Beta, and Beta remains the right home for testers. If you were on Developer, PyReconstruct now keeps you on Beta automatically, so you do not need to change anything. To follow the very latest code between betas, install from source and run "git pull" (see the README).

## [1.21.0-beta-4] — 2026-07-18

- **A trace's new color now shows immediately, everywhere.** Changing a trace's color could leave the trace drawn in its old color (while its selection highlight already showed the new one) until the view was fully redrawn. Thanks to Lyndsey for spotting and reporting this one!
- **Undo now works correctly for objects with accented or non-English names.** On some Windows systems, undoing right after editing an object whose name contained special characters (accents, non-Latin scripts) could fail or even wipe the object's traces. Your traces are now always restored intact.
- **Series files play nicely with the standard PyReconstruct again.** Files saved by this version now open correctly in the regular (SynapseWeb) PyReconstruct on any computer — non-English object names and comments no longer risk turning into garbled text for collaborators.
- **Smoother image-to-Zarr conversion on modest computers.** Converting images to a scaled Zarr no longer overwhelms every CPU core, so your laptop stays usable while it runs. The "CPU usage" slider in Series ▸ Options now genuinely controls how much of your processor the conversion uses (with tick marks and a short explanation), and it defaults to about half your cores. Turn it up for maximum speed on a powerful machine, or down if things feel sluggish.

## [1.21.0-beta-3] — 2026-07-17

- **You choose whether the 3D scene updates itself.** The 3D view normally refreshes your edited objects the moment you return to it. If you'd rather it wait — say, while making many edits on a large series — you can now turn auto-refresh off, from the 3D window's Scene menu or in Series ▸ Options. "Refresh edited objects" (Ctrl+R) still works anytime, and turning auto-refresh back on catches the scene up right away.
- **Clearer names for update channels.** In Series ▸ Options ▸ Updates, "Release" is now **Stable (recommended)** and "Pre-release" is now **Beta (early features, may be unstable)** — same channels, clearer names. You're reading these notes because you're on Beta — thank you!
- **A new Developer channel for the adventurous.** A third update channel installs the very latest build after every single change we merge — no waiting for a beta. Expect rough edges; Beta remains the right home for most testers.

## [1.21.0-beta-2] — 2026-07-15

- **Fewer save interruptions on Windows.** An occasional "Save failed" message could pop up while you were just scrolling between sections. PyReconstruct now waits a moment and retries, so these hiccups no longer interrupt you. (Your work was always safe; the message appeared even though the file was left untouched.)
- **The window won't open tiny anymore.** Fixed the main window sometimes opening very small, or off-screen, after moving between monitors with different scaling, like an external display and a laptop's high-resolution screen. It now opens at a sensible size and position.
- **Easier to report a problem.** When something goes wrong, the error window now has a "Copy report to clipboard" button that gathers everything we need (what happened, your version, and your operating system) so you can paste it straight into a bug report or email. You can also grab this anytime from Help, Report issues, Copy diagnostic report.
- **See PyReconstruct's log.** New Help, View log file (and Open log folder) let you look at the behind-the-scenes messages that used to appear only in a console window. This is handy when something misbehaves or you're sending us a report.
- **A clearer default when converting images to Zarr.** Converting images to a scaled Zarr now suggests a clearer name and place: a `<series>.zarr` folder right next to your images. You can still choose your own name and location.

## [1.21.0-beta-1] — 2026-07-07

- **Copy traces to multiple sections at once.** Select traces, right-click, choose "Copy to sections," and place them at the same spot across a range of sections in one step.
- **Propagate an alignment by correlation across sections.** After aligning a section with Align by correlation (`Ctrl+\`), you can now propagate that shift across a range of sections, the way you already can with a manual transform.
- **Isolate the objects you're working on.** "Hide other objects" hides everything except your selection across the whole series, so your object stays isolated as you page through sections. "Show all objects" brings them back, and "Hide all objects" clears the view so you can reveal objects a few at a time. Look in the object list's new Selection menu or the right-click menu.
- **Invert a selection in one step.** Flip which objects are selected in the object list, or which traces are selected on the current section, so you can pick a few and instantly switch to all the rest.
- **Clearer colors for imported traces.** Traces brought in from automatic segmentation now get distinct, easy-to-tell-apart colors that also work well for colorblind viewers and stand out against the grayscale image. The colors you see while importing match the final result, and you can shuffle them if you'd like a different set.
- **The 3D scene keeps up with your edits.** Changes to your 2D traces now show up right away in an open 3D view, instead of it showing a stale 3D object until you remove and add back/reload the object in the 3D scene.
- **Re-read release notes anytime.** The Help menu now includes "What's new," which reopens this summary on demand so you can revisit what changed after the update popup is gone.
- **A browsable user guide.** The full user guide is now a searchable wiki with a page for each topic, reachable from Help, Online resources.

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

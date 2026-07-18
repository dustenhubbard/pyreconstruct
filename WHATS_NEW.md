# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [1.21.0-beta-3] — 2026-07-17

- **You choose whether the 3D scene updates itself.** The 3D view normally refreshes your edited objects the moment you return to it. If you'd rather it wait — say, while making many edits on a large series — you can now turn auto-refresh off, from the 3D window's Scene menu or in Series ▸ Options. "Refresh edited objects" (Ctrl+R) still works anytime, and turning auto-refresh back on catches the scene up right away.
- **Clearer names for update channels.** In Series ▸ Options ▸ Updates, "Release" is now **Stable (recommended)** and "Pre-release" is now **Beta (early features, may be unstable)** — same channels, clearer names. You're reading these notes because you're on Beta — thank you!
- **A new Developer channel for the adventurous.** A third update channel installs the very latest build after every single change we merge — no waiting for a beta. Expect rough edges; Beta remains the right home for most testers.
- **Smoother image-to-Zarr conversion on modest computers.** Converting images to a scaled Zarr no longer overwhelms every CPU core, so your laptop stays usable while it runs. The "CPU usage" slider in Series ▸ Options now genuinely controls how much of your processor the conversion uses (with tick marks and a short explanation), and it defaults to about half your cores. Turn it up for maximum speed on a powerful machine, or down if things feel sluggish.

## [1.21.0-beta-2] — 2026-07-15

- **Fewer save interruptions on Windows.** An occasional "Save failed" message could pop up while you were just scrolling between sections. PyReconstruct now waits a moment and retries, so these hiccups no longer interrupt you. (Your work was always safe; the message appeared even though the file was left untouched.)
- **The window won't open tiny anymore.** Fixed the main window sometimes opening very small, or off-screen, after moving between monitors with different scaling, like an external display and a laptop's high-resolution screen. It now opens at a sensible size and position.
- **Easier to report a problem.** When something goes wrong, the error window now has a "Copy report to clipboard" button that gathers everything we need (what happened, your version, and your operating system) so you can paste it straight into a bug report or email. You can also grab this anytime from Help, Report issues, Copy diagnostic report.
- **See PyReconstruct's log.** New Help, View log file (and Open log folder) let you look at the behind-the-scenes messages that used to appear only in a console window. This is handy when something misbehaves or you're sending us a report.
- **A clearer default when converting images to Zarr.** Converting images to a scaled Zarr now suggests a clearer name and place: a `<series>.zarr` folder right next to your images. You can still choose your own name and location.

## [1.21.0-beta-1] — 2026-07-07

- **Copy traces to multiple sections at once.** Select traces, right-click, choose "Copy to sections," and place them at the same spot across a range of sections in one step.
- **Propagate an alignment by correlation across sections.** After aligning a section with Align by correlation (`Ctrl+\`), you can now propagate that shift across a range of sections, the way you already can with a manual transform.
- **Isolate the objects you're working on.** "Hide Other Objects" hides everything except your selection across the whole series, so your object stays isolated as you page through sections. "Show all objects" brings them back, and "Hide all objects" clears the view so you can reveal objects a few at a time. Look in the object list's new Selection menu or the right-click menu.
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

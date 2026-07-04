# What's New

Short, plain-language highlights shown in PyReconstruct's "What's new" dialog
after you install or update. For the complete, detailed list of changes, see the
full release notes on GitHub (linked from the dialog).

## [1.20.5rc1] — 2026-07-04

- **Your work is better protected.** Fixed several cases where edits could be lost or a file corrupted, including edits made right before flicking to another section and saves interrupted by a crash or a full disk.
- **Safer handling of shared files.** Hardened how PyReconstruct opens and converts series files received from others.
- **Align by correlation fixed.** It now applies the correlation shift correctly even when the section is rotated or scaled.
- **Smoother on large series.** Faster hovering and rendering, plus more reliable background exports and updates.

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

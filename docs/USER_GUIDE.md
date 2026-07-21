# PyReconstruct User Guide

PyReconstruct is a desktop application for tracing, annotating, and
3D-reconstructing serial-section and volume electron-microscopy (EM) data. This
guide covers installing the app, opening and building a series, the tracing
tools, the data lists, alignment, 3D reconstruction, and backups.

This guide describes the application as it currently behaves in this
distribution. It complements the in-app help (**Help ▸ Online resources ▸
PyReconstruct user guide**, which opens the
[lab wiki](https://wikis.utexas.edu/display/khlab/PyReconstruct+user+guide) at
The University of Texas at Austin) and the in-app **Help ▸ Shortcuts list**.

> **About screenshots.** This guide does not ship screenshots yet. Places where
> a screenshot would help are marked like this:
>
> > 📸 *Screenshot: short description of what to capture.*
>
> Contributions of screenshots are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).

> **Shortcuts.** Key combinations shown here are the **defaults**. Almost all of
> them are rebindable under **Help ▸ Shortcuts list** (press `?`). A few menu
> shortcuts are fixed: `PgUp`/`PgDown` (section navigation), `Home` (fit view),
> `Ctrl+\` (align by correlation), and `?` (the shortcuts list itself).

---

## Contents

1. [Installing PyReconstruct](#1-installing-pyreconstruct)
2. [Keeping PyReconstruct up to date](#2-keeping-pyreconstruct-up-to-date)
3. [Core concepts](#3-core-concepts)
4. [Opening and creating a series](#4-opening-and-creating-a-series)
5. [The main window and navigation](#5-the-main-window-and-navigation)
6. [The tool palette](#6-the-tool-palette)
7. [The trace palette](#7-the-trace-palette)
8. [Working with traces](#8-working-with-traces)
9. [Data lists](#9-data-lists)
10. [Alignment](#10-alignment)
11. [3D reconstruction](#11-3d-reconstruction)
12. [Saving and backups](#12-saving-and-backups)
13. [Keyboard shortcuts](#13-keyboard-shortcuts)
14. [Getting help](#14-getting-help)
15. [Credits](#credits)

---

## 1. Installing PyReconstruct

There are two ways to install PyReconstruct: a one-click installer (recommended
for most users) or a from-source install with `pip` (for developers and other
platforms).

### One-click installers (Windows, macOS, and Linux)

Download the latest build from
**[Releases](https://github.com/dustenhubbard/PyReconstruct/releases)** — no
Python required.

- **Windows** — `PyReconstruct-<version>-Windows-x86_64-Setup.exe`. This is a
  per-user installer (no administrator rights required). Builds are unsigned for
  now, so Windows SmartScreen may warn that the publisher is unknown; choose
  **More info ▸ Run anyway**. Re-running a newer installer upgrades the existing
  installation in place.
- **macOS (Apple Silicon or Intel)** — `PyReconstruct-<version>-macOS-arm64.dmg` on
  Apple Silicon, or `PyReconstruct-<version>-macOS-x86_64.dmg` on an Intel Mac. Open
  the `.dmg` and drag **PyReconstruct** onto the **Applications** shortcut. Builds are
  unsigned for now, so the first launch of a browser-downloaded copy is blocked by
  Gatekeeper. Clear the quarantine flag once in Terminal:

  ```
  xattr -dr com.apple.quarantine /Applications/PyReconstruct.app
  ```

  Alternatively, the first time macOS shows the "could not verify" dialog, open
  **System Settings ▸ Privacy & Security** and click **Open Anyway**.

> 📸 *Screenshot: the macOS `.dmg` window showing the app and the Applications drop target.*

Both macOS builds are native (arm64 and x86_64), and the in-app updater serves each
Mac its matching architecture.

- **Linux** — `PyReconstruct-<version>-Linux-installer.tar.gz`. Extract it and run
  `bash install.sh` — a no-root `.sh` installer that builds an isolated virtual
  environment, puts a `pyreconstruct` launcher on your PATH, and adds an
  application-menu entry. It needs a system **Python 3.11** (`python3.11` + `venv`;
  on Debian/Ubuntu, `sudo apt install python3.11 python3.11-venv`) and targets
  x86_64. To update, re-run `install.sh`.

### From source (Linux, other platforms, and developers)

PyReconstruct requires **Python 3.11** — the pinned version the app and its
native dependencies are validated on (the project pins `>=3.11,<3.12`). Your
system `python3` is likely newer, and installing against it will fail; the steps
below get you 3.11 without changing your system Python. The recommended tool is
[uv](https://docs.astral.sh/uv/), which downloads Python 3.11 for you — install
it with `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`).

For a quick, non-editable install into a fresh 3.11 environment:

```
uv venv --python 3.11 && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install git+https://github.com/dustenhubbard/PyReconstruct
PyReconstruct
```

`pip` pulls in the runtime dependencies (PySide6, VTK, vedo, NumPy, SciPy,
scikit-image, shapely, trimesh, zarr, and others). If you already have
`python3.11` on PATH, plain `venv` works instead of `uv`: `python3.11 -m venv
.venv && source .venv/bin/activate`, then `pip install git+…`.

To **track the latest unreleased code on `main`** (what the retired in-app
"Developer" channel used to offer), clone the repository and let uv build the
environment from the committed `uv.lock`. This is the canonical developer setup:
`uv sync` reads the Python 3.11 pin, provisions the interpreter, and installs the
exact pinned dependency set.

```
git clone https://github.com/dustenhubbard/PyReconstruct
cd PyReconstruct
uv sync                            # creates .venv from uv.lock (exact pinned deps)
uv run PyReconstruct               # launch
```

To move to the newest `main` later: `git pull`, then `uv run PyReconstruct` —
`uv run` re-syncs `.venv` to the lockfile automatically, so there is no manual
reinstall step.

If you prefer a plain `venv` and already have `python3.11` on PATH, an editable
install works too, though it resolves dependencies fresh rather than from
`uv.lock`: `python3.11 -m venv .venv && source .venv/bin/activate`, then
`pip install -e .` (rerun only when `pyproject.toml` changes; a bare `git pull`
otherwise suffices).

For a full development setup (test suite, dev tooling, the parallel conda
`pyrecon_dev` environment, code layout), see
[CONTRIBUTING.md](../CONTRIBUTING.md) and [DEV_UV.md](DEV_UV.md).

### Launching the app

- From an installer: launch **PyReconstruct** like any other installed application.
- From a source install: run `PyReconstruct` on the command line.

The command accepts a few optional flags, e.g. `PyReconstruct -f path/to/series.jser`
to open a series directly on launch. (Run `PyReconstruct --help` for the full
list.)

---

## 2. Keeping PyReconstruct up to date

The frozen Windows and macOS one-click builds can update themselves from within the
app. The updater downloads the new build from GitHub Releases and **verifies it
against a published SHA-256 checksum before installing** — if the checksum can't be
reached or doesn't match, nothing is installed. (The Linux `.sh` installer updates
by re-running `install.sh` — see [Installing PyReconstruct](#1-installing-pyreconstruct).)

### Update channels

PyReconstruct offers two update channels, selected under **Series ▸ Options…**
(`Shift+O`) in the **Updates** section:

- **Stable (recommended)** — stable builds, tagged `vX.Y.Z`.
- **Beta (early features, may be unstable)** — the latest pre-release build (release
  candidates, tagged like `vX.Y.ZrcN`); newer features, less testing.

The default channel is **Stable**. (Developers who want the newest unreleased code
run a source install instead of a frozen build — see
[Source / `pip` installs](#source--pip-installs) below.)

> 📸 *Screenshot: Series ▸ Options ▸ Updates, showing the Stable / Beta radio buttons and the "Check for updates on startup" checkbox.*

### Checking for updates

Choose **Help ▸ Check for updates…**. On an installed build, PyReconstruct checks
GitHub Releases on your selected channel (off the main thread, so the UI stays
responsive). If a newer build is found, an update dialog opens showing the new
version, the download size, and the release notes, with a **Download & Install**
button. The download is verified, then applied when you close the app, and
PyReconstruct restarts on the new version.

If you are already current, you'll see a brief "You're already up to date"
message; if no installer exists for your platform on that channel, it tells you so.

> 📸 *Screenshot: the "PyReconstruct — Update" dialog with release notes and the Download & Install button.*

### Checking automatically on startup

Under **Series ▸ Options ▸ Updates** you can enable **Check for updates on
startup**. It is **off by default**. When enabled, an installed build does a quiet
background check at most **once per day**; if an upgrade is available it shows a
status-bar notice and asks whether you'd like to view it.

### Source / `pip` installs

For a from-source install, **Help ▸ Check for updates…** instead reinstalls
PyReconstruct from a chosen Git branch with `pip` and then restarts. The branch is
configured under **Series ▸ Options ▸ Updates** (the **Branch:** field, default
`main`). The channel/installer machinery above applies only to packaged builds.

The same reinstall is available from the command line: `PyReconstruct --update`
(reinstall the current branch) or `PyReconstruct --switch <branch>` (change branch,
then reinstall). If you installed editable (`pip install -e .`), a plain `git pull`
is usually all you need — the working tree is what runs. A source install on `main`
is the supported way to follow every commit now that the in-app Developer channel
has been removed.

---

## 3. Core concepts

PyReconstruct is organized around serial-section microscopy: a block of tissue is
cut into an ordered stack of thin sections, each imaged, and structures are traced
through the stack.

- **Series** — a complete project: an ordered set of sections plus series-wide
  settings. You work on one series at a time. A series is stored as a single
  `.jser` file (see below).
- **Section** — one cross-section in the stack. Each section has an index, a
  background **image**, a **magnification** (`mag`, in µm per image pixel), a
  **thickness** (in µm), brightness/contrast, and its own set of traces.
- **Trace** — a single connected shape or curve drawn on one section. A trace can
  be **closed** (an outline enclosing area, e.g. a cell cross-section) or **open**
  (a curve with length but no enclosed area, e.g. a process or a measurement line).
- **Contour** — all traces with the same name **on a single section**.
- **Object** — all traces with the same name **throughout the whole series**.
  Objects are what you reconstruct in 3D and measure in the object list.
- **Z-trace** — a single curve that runs **across sections** (its points carry a
  section index), used to measure distances through the volume.
- **Flag** — a labeled, optionally colored marker placed at a point on a section,
  with comments and a resolved/unresolved state. Flags are useful for to-do notes,
  questions, and review.
- **Transform** — a section's affine transform, six numbers `a b c d e f`: `a b d
  e` give rotation/shear/scale and `c f` give x/y translation. The **same**
  transform is applied to the section's image *and* its traces, so traces stay
  fixed to the image — moving the alignment moves image and traces together.
- **Alignment** — a named set of per-section transforms across the whole series. A
  series can hold several alignments and you can switch between them. (See
  [Alignment](#10-alignment).)
- **Host / traveler** — an optional parent/child relationship between objects: an
  object can be hosted by ("ride on") another object. Used to keep related
  structures organized and to group them in the 3D scene.

### The `.jser` file

A series is saved as a single `.jser` file. It is a JSON document with the
series-level settings, the per-section data (including each section's image
filename, magnification, and thickness), and the edit log. **The `.jser` does not
contain the images themselves** — it stores image filenames, and the actual image
files live in the series' image source directory. While a series is open,
PyReconstruct unpacks it into a hidden working folder next to the `.jser` and
repacks on save.

### Images and Zarr

Supported image formats for sections are **JPG/JPEG, PNG, TIF/TIFF, and BMP**.

For large images, PyReconstruct can use multiscale **Zarr** image stores, which
load only the parts of the image needed for the current view (rather than the
whole image on every section change). You can convert a series' images to scaled
Zarr from **Series ▸ Images ▸ Convert to scaled images** (see
[Opening and creating a series](#4-opening-and-creating-a-series)).

---

## 4. Opening and creating a series

### On first launch

With no file specified, PyReconstruct opens a **welcome series** — a small,
read-only demo you can use to explore the interface. The welcome series cannot be
saved or backed up; create or open a real series to begin work. A **username** is
resolved automatically and recorded against the edits you make — PyReconstruct no
longer prompts for it on launch; change it anytime under **File ▸ Change
username…**.

### Opening an existing series

**File ▸ Open** (`Ctrl+O`) opens a `.jser` file. Recently opened series are listed
under **File ▸ Open recent**. **File ▸ Close** returns to the welcome series (it
does not quit the app).

If a series' image files can't be found when it opens, PyReconstruct asks whether
you'd like to locate them and lets you pick the image folder (you can also do this
later via **Series ▸ Images ▸ Find/change image directory**).

**Recovering an unsaved session.** If a series was left open or not saved cleanly
(for example after a crash), reopening it detects the leftover working folder and
offers to recover the unsaved session. If the same series appears to be open in
another window (it was touched within the last few seconds), PyReconstruct shows
**"Series In Use"** and declines to open a second copy.

### Creating a new series from images

**File ▸ New ▸ From images…** (`Ctrl+N`) walks you through:

1. **Select images** — choose the section image files (JPG/JPEG, PNG, TIF/TIFF,
   BMP). The files are sorted alphanumerically, and that order becomes the section
   order (section 0, 1, 2, …), so name your images so they sort correctly.
2. **Series name** — used to name the series.
3. **Image calibration (µm/px)** — microns per image pixel. Default **0.00254**.
4. **Section thickness (µm)** — default **0.05**. Thickness feeds the volume and
   flat-area calculations in the object list.

The new series opens fitted to the first image; you are then prompted to choose
where to save the `.jser`.

> 📸 *Screenshot: the New Series calibration / thickness prompt.*

### Other ways to create a series

Also under **File ▸ New**:

- **From scaled images…** — build from an existing scaled Zarr directory (expects
  a `scale_1` folder), then the same name/calibration/thickness prompts.
- **From legacy .ser…** — create from legacy *Reconstruct* XML `.ser` files.
- **From neuroglancer zarr…** — create from a Neuroglancer Zarr.

### Image directory and Zarr conversion

Under **Series ▸ Images**:

- **Find/change image directory** — point the series at the folder containing its
  images. The chosen directory is remembered with the series.
- **Convert to scaled images** — convert the series' images into a scaled
  (`.zarr`) store for faster loading of large images.
- **Update image scales** — add or refresh scale levels on an existing Zarr.

---

## 5. The main window and navigation

The main window shows the current section's image with its traces drawn on top
(the **field**). Floating overlays sit on top of the field: the **tool palette**
(the column of mode buttons, top-right by default), the **trace palette** (the row
of preset traces, bottom-center), section-increment buttons, brightness/contrast
sliders, and a scale bar. Each overlay group can be dragged to reposition it, and
**View ▸ Reset palette position** restores the defaults.

> 📸 *Screenshot: the main window labeled — field, tool palette (right), trace palette (bottom), scale bar (bottom-left), section-increment buttons.*

### Moving between sections

- **Page Up** / **Page Down** — next / previous section.
- **Mouse wheel** over the field — scroll up for the next section, down for the
  previous (works in any tool mode).
- **Go to section** (`Ctrl+G`) — jump to a section number.
- The section-increment buttons (▲/▼) in the corner do the same as PgUp/PgDown
  (handy on tablets).

### Panning and zooming (in any tool)

- **Middle-click and drag** — pan the view.
- **Ctrl + mouse wheel** — zoom about the cursor.
- **Home** — fit the view to the image. **View ▸ View magnification…** sets an
  exact zoom (useful for consistent figure scale).

The dedicated **Pan/Zoom** tool (below) is an alternative when a middle mouse
button isn't available.

### Brightness and contrast

Adjust the current section with the corner sliders, or with the keyboard:
brightness `=` / `-`, contrast `]` / `[` (also under **Edit ▸ Brightness/contrast**).
Named brightness/contrast profiles are available under **Series ▸ Brightness/contrast
profiles…**.

### Showing and hiding interface elements

Under **View ▸ Palette ▸ Visibility** you can independently toggle the trace
palette, the section-increment buttons, the brightness/contrast sliders, and the
scale bar. **View ▸ Left handed** swaps the tracing-pencil cursor side.

### Theme

**View ▸ Change theme** offers **Default** and **Dark**. (The theme can also be set
under **Series ▸ Options**.)

---

## 6. The tool palette

The tool palette is the column of mode buttons (top-right by default). Click a
button — or press its shortcut — to switch the active tool. **Right-clicking a
tool button opens that tool's settings** (where it has any).

In every tool except Pan/Zoom, **right-clicking the field** opens a context menu
(for the selected traces, or for the field). The mouse wheel changes sections, and
middle-click pans, regardless of the active tool.

The palette has eleven tools:

### Pointer (`P`)

Selects and moves traces, z-trace points, and flags.

- **Click** a trace to select/deselect it.
- **Click and drag on empty space** to draw a selection region. By default this is
  a freehand **lasso** that selects only fully-enclosed traces; right-click the
  Pointer button to switch the region shape (**Rectangle**/**Lasso**) and whether
  it selects **all touched** traces or **only completely encircled** ones.
- **Click and drag a selected trace** to move all selected items together.

### Pan/Zoom (`Z`)

- **Drag** with the left button to pan.
- **Drag up/down** with the right button to zoom.

(Pan and zoom are also available in any tool via middle-click and Ctrl+wheel.)

### Knife (`K`)

Slices a selected trace along a freehand line.

- Select the trace(s) to cut first (they must share one object name and be all
  open or all closed), then **drag** the knife across them.
- Resulting pieces smaller than a threshold percentage of the original are
  discarded — right-click the Knife button to set **% original trace** (default
  **1.0**) and to enable **Smooth cuts**.

### Scissors

Re-traces an existing trace. **Click a trace** and the tool reopens it as a live
line starting at the clicked point, so you can re-draw it; **right-click** to
finish. Useful for fixing part of a contour without redrawing the whole thing.
(Scissors has no default keyboard shortcut.)

### Closed Trace (`C`) and Open Trace (`O`)

Draw new traces with the current trace-palette preset's name and color. **Closed
Trace** makes outlines that enclose area; **Open Trace** makes curves with length
only.

Right-click either button to choose the drawing **mode**:

- **Scribble** — hold and drag to draw freehand; release to finish.
- **Poly** — click to place each vertex; **right-click to finish**; **Backspace**
  removes the last point.
- **Combo** (default) — a quick click starts a poly/clicked line; click-and-drag
  scribbles.

For **Closed Trace** you can also pick a fixed **shape** — freehand **Trace**,
**Rectangle**, or **Ellipse** (drag to size) — and optionally auto-merge new traces
into selected same-named traces, or apply a rolling-average smooth while
scribbling.

### Stamp (`S`)

Places a copy of the current trace-palette preset's shape at a fixed size.

- **Click** to drop one stamp centered on the cursor at the preset's radius.
- **Click and drag** to set the radius for that stamp (diameter = drag distance).

The stamp shape and its radius come from the selected trace-palette button (set
them by right-clicking that button — see [The trace palette](#7-the-trace-palette)).

### Grid (`G`)

Replicates the current preset into a rectangular array — useful for stereology
sampling. **Click** to place the grid. Right-click the Grid button to set the
element size, spacing, and number of columns/rows. With **Sampling frame** enabled
(the default), each cell is drawn as a counting frame (a red exclusion line and a
green inclusion line) rather than a copy of the preset.

### Flag (`F`)

Drops a labeled marker (a `⚑` glyph) at the clicked point. **Click** to place a
flag and fill in its name, color, and an optional comment. Right-click the Flag
button to set the default name/color, the flag size, and which flags are shown:
**All flags**, **Only unresolved flags** (the default), or **No flags**.

Flags are selected and moved with the Pointer tool; **right-clicking a flag** opens
its dialog, where you can edit its name/color, add comments, and mark it
**Resolved**. All flags in the series are listed in the [Flag list](#9-data-lists).

### Host (`Q`)

Sets host (parent) relationships between objects. **Click a first trace** (the
object that will be hosted), then **click a second trace** (its host); a line is
drawn between them while you choose. **Right-click** to cancel. An object can't host
itself, and two objects can't host each other. Hosts also appear as a column in the
object list and can be set from the object list's context menu.

### Z-trace tool

Creates a [z-trace](#3-core-concepts) — a curve through the stack. Select the
tool, then **click** points (changing sections between clicks as needed with the
mouse wheel); **right-click to finish**. The new z-trace takes the current
preset's name and color. (This tool is selected from the palette; it has no default
keyboard shortcut.)

---

## 7. The trace palette

The trace palette is the row of preset traces at the bottom of the window. The
selected preset supplies the **name, color, tags, shape, and stamp radius** for new
traces you draw, stamp, or grid. The selected preset's name is shown (in its color)
near the palette.

- The default palette has **20 presets**, arranged as two rows of ten.
- Select a preset with the number keys: **`1`–`9`, `0`** for the first row, and
  **`Shift+1`–`Shift+9`, `Shift+0`** for the second.
- **Right-click a preset** (or press `Ctrl`+its number) to edit its attributes —
  name, color, fill mode, tags, the trace **shape**, and the **stamp radius
  (microns)** used by the Stamp and Grid tools.

The small buttons beside the palette let you bulk-increment numbered preset names
(`+`/`−`, applied to all presets or only the active one), open **Modify all
palettes**, and show help. Preset names containing a number pattern can also
auto-increment as you place traces, which is handy for numbering a sequence of
objects.

You can reset the palette (**Series ▸ Trace palette ▸ Reset current palette**) and
export/import palettes as CSV (**Series ▸ Trace palette ▸ Export as CSV… / Import
from CSV…**). **Edit ▸ Paste attributes to palette** (`Shift+G`) sets the current
preset from a copied trace.

> 📸 *Screenshot: the trace palette with the right-click "edit trace attributes" dialog open, showing the Stamp radius field.*

---

## 8. Working with traces

Most trace editing is on the **field context menu** (right-click selected traces),
with keyboard shortcuts for the common actions. Selected-trace actions affect *all*
selected traces. The top of that menu carries a single **Edit ... attributes...**
shortcut that follows your selection — it reads **Edit trace attributes...** when
traces are selected and **Edit z-trace attributes...** when z-traces are, so the
most-used edit is one click away above the per-entity submenus.

- **Edit attributes** (`Ctrl+E`) — change name, color, tags, and fill mode.
- **Merge traces** (`Ctrl+M`) — merge the exteriors of selected traces (they must
  share a name).
- **Hide** (`Ctrl+H`) / **Unhide all** (`Ctrl+U`) — hidden traces can't be edited
  until unhidden.
- **Make negative / positive** — negative traces subtract from (cut into) the area
  of same-named traces, e.g. to carve a hole; this matters for area and 3D volume.
- **Cut / Copy / Paste** (`Ctrl+X` / `Ctrl+C` / `Ctrl+V`) and **Paste attributes**
  (`Ctrl+B`) — copy a trace's name/color/tags onto selected traces.
- **Delete** (`Delete` or `Backspace`) — delete the selected traces.

On the field (right-click empty space, or use the shortcuts):

- **Select all** (`Ctrl+A`) / **Deselect** (`Ctrl+D`).
- The **View** submenu items are checkboxes that show their current on/off state;
  each also has a keyboard shortcut that toggles it:
  - **Hide trace layer** (`H`) and **Show all traces (ignore hidden)** (`A`) —
    temporarily hide or show every trace regardless of individual hidden state
    (the field border turns red when all are force-hidden, green when all are
    force-shown). These differ from per-trace Hide/Unhide.
  - **Section blend** (`Space`) — blend the current and last-viewed section, to
    compare them.
  - **Hide image** (`I`), **Focus mode** (`X`).

**Undo** (`Ctrl+Z`) / **Redo** (`Ctrl+Y`) cover actions on the field. (Some edits
made through the lists are noted there as not undoable.)

**Find a contour** on the current section with **Section ▸ Find contour…**
(`Shift+F`); jump to an object's first contour anywhere in the series with
**Series ▸ Find first object contour…** (`Ctrl+F`).

---

## 9. Data lists

PyReconstruct provides five list/table windows, plus a series history window, under
the **Lists** menu. Each list opens as a dockable panel (multiple instances are
allowed), and several can be open at once.

| List | Open with | Shows |
|---|---|---|
| **Object list** | `Ctrl+Shift+O` | every object in the series, with quantities and attributes |
| **Trace list** | `Ctrl+Shift+T` | traces on the **current section** |
| **Section list** | `Ctrl+Shift+S` | every section |
| **Z-trace list** | `Ctrl+Shift+Z` | every z-trace |
| **Flag list** | `Ctrl+Shift+F` | flags across the series |
| **Series history** | (no shortcut) | the full edit log |

### Features shared by the lists

- **Set columns…** — choose which columns are shown and reorder them.
- **Export…** — write the displayed columns/rows to CSV.
- **Refresh** — reload from the series data (the object list also auto-refreshes as
  you trace; the trace list has no separate Refresh — it tracks the current
  section).
- **Filters** — most lists filter by a **regex** on the name (where `#` is
  shorthand for a digit), and by **group** and/or **tag** where applicable.
- **Ctrl+C** copies selected cells. **Delete/Backspace** deletes the selected rows'
  underlying data. Right-click a selection for that list's context menu.
- Every list's context menu offers **Invert selection** (select the displayed rows
  that aren't selected, and vice versa — it only ever acts on rows currently shown,
  so an active filter is respected) and **Copy _entity_ values** (named for the list —
  **Copy object values**, **Copy trace values**, etc.; the same as `Ctrl+C`).

> 📸 *Screenshot: the Object list docked on the left, with the column/filter menus visible.*

### Object list

Double-click an object to jump to its first occurrence; **Shift+double-click** adds
it to the 3D scene. Columns include **Name**, **Start/End** (first/last section),
**Count**, **Flat area**, **Volume**, **Radius**, **Host**/**Superhosts**,
**Groups**, **Trace tags**, **Locked**, **Last user**, **Comment**, **Configuration**
(open/closed/mixed), an optional **Curate** state, and any custom **categorical**
columns you define.

- **Flat area** = the summed closed-trace areas plus open-trace lengths × section
  thickness; **Volume** = summed closed-trace areas × section thickness.
- The context menu edits the object across the whole series: edit attributes, set
  comments/hosts/groups/alignment, lock/unlock, create a copy, edit radius/shape,
  smooth, split into individual objects, set curation, manage the object in 3D
  (add/remove/export meshes/export quantitative data/edit 3D settings), create a
  z-trace from it, view history, and delete.
- **Filters**: regex, group, tag, curation, configuration, and host filters.
- **Find ▸ First / Last** jump to the object's first/last section.
- The **Curate** columns can be toggled across all object lists with
  **View ▸ Toggle curation in object lists** (`Ctrl+Shift+C`).

### Trace list

Lists traces on the current section (it follows you as you change sections).
Columns include **Name**, **Index**, **Tags**, **Hidden**, **Closed**, **Length**,
**Area**, **Radius**, optional **Centroid** and **Feret** diameters. **List ▸
Export all traces in series…** writes every trace in the series to CSV. The context
menu can edit/smooth/merge traces, set open/closed, make negative/positive, hide,
edit shape/radius, create a flag on a trace, and delete.

### Section list

Lists all sections. Columns: **Section** (number; calibration-grid sections are
marked), **Thickness**, **Locked**, **Brightness**, **Contrast**, **Image Source**.
The context menu locks/unlocks sections, sets brightness/contrast (set, increment,
match to the in-view section, or optimize), edits thickness, edits the image source,
inserts a section above/below, copies, and deletes. **Modify ▸ Section image
sources…** bulk-renames image sources, and **Reorder sections** renumbers them
sequentially.

### Z-trace list

Lists all z-traces. Columns: **Name**, **Start**, **End**, **Distance** (length),
**Groups**, **Alignment**. The context menu edits attributes, smooths, manages the
z-trace in 3D and in groups, changes its alignment, and deletes.

### Flag list

Lists flags across the series; resolved flags are hidden by default. Columns:
**Section**, **Color**, **Flag** (name), **Resolved**, **Last Comment**.
Double-click jumps to the flag. The context menu opens the flag to view/edit and
add comments, marks flags resolved/unresolved, filters by color, copies, deletes,
or deletes all flags with a given name. Filters include showing resolved flags, a
name regex, a color filter, and a comment-text filter.

### Series history

**Lists ▸ Series history** opens a read-only **History** window (Date, Time, User,
Object, Sections, Event), newest first. The object list's **View history** shows
the same window filtered to the selected objects. Long histories can be trimmed
with **Series ▸ Log ▸ Offload log history…**, which exports older entries to an
external CSV.

---

## 10. Alignment

An **alignment** is a named set of per-section transforms. The currently active
alignment determines how each section's image and traces are positioned. Switching
alignments never changes the underlying images or trace coordinates — only how they
are displayed.

Every series includes a special **`no-alignment`** entry (the identity transform).
It can't be edited, renamed, or deleted, and you can't edit transforms while it is
active — switch to a real alignment first.

### Switching and managing alignments

- **Switch** the current alignment from the field's right-click menu (**Series
  alignment** submenu), which lists every alignment as a checkable item.
- **Alignments ▸ Edit alignments…** (`Ctrl+Shift+A`) opens the alignment dialog,
  where you can create a **New** alignment (created as a copy of the current one),
  **Rename**, or **Remove** alignments. Objects can also carry a per-object
  alignment override (**Edit alignment…** in the object list).

### Adjusting a section's transform

- **Alignments ▸ Edit transformation** (`Ctrl+T`) — enter the six transform numbers
  `a b c d e f` directly. (Blocked on locked sections and while in `no-alignment`.)
- **Keyboard nudges** (when no traces are selected, these move the section's
  transform; otherwise they move the selected traces):
  - Arrow keys — translate (medium step); `Ctrl`+arrows = small, `Shift`+arrows =
    big. Step sizes are set in **Series ▸ Options**.
  - `Ctrl+Shift+Left` / `Ctrl+Shift+Right` — rotate about the cursor.
  - `F1`–`F4` (with `Shift` to reverse) — scale and shear in X/Y.

### Assisted alignment

- **Estimate affine transform** — align the current section to the comparison ("B")
  section from matched traces. Select **3 or more** traces of the same name on both
  sections (the same number on each); PyReconstruct computes the affine transform
  that best maps one set of centroids onto the other.
- **Align by correlation** (`Ctrl+\`) — automatically register the current image to
  the section beneath it by image cross-correlation (a translation-only adjustment).
- **Propagate transform** — record a transform adjustment and apply it across many
  sections: **Start propagation recording**, make your adjustment, then **Propagate
  to start** / **Propagate to end** (or simply navigate — while recording, moving to
  a new unlocked section applies the recorded change). A red dot is shown on the
  field while recording. Locked sections are skipped.

### Align by correlation, then propagate across a range

The `Ctrl+\` correlation shift can be recorded and propagated across a range of
sections, exactly like a manual transform — but **you must start recording before
you correlate**:

1. Navigate to the section you want to align.
2. **Alignments ▸ Propagate transform ▸ Start propagation recording**.
3. Press `Ctrl+\` (**Align by correlation**). This aligns the current section and
   records the shift.
4. Either navigate through the sections (each unlocked section you visit receives
   the recorded shift) or use **Propagate to start** / **Propagate to end** to apply
   it across a bulk range at once.
5. **Alignments ▸ Propagate transform ▸ End propagation recording**.

Order matters: starting recording resets the accumulator, so pressing `Ctrl+\`
*before* you start recording will not capture that alignment — always start
recording first. As with manual transforms, locked sections are skipped during
propagation.

### Importing transforms

**Alignments ▸ Import alignments**:

- **.txt file** — one line per section: `section a b c d e f` (the integer section
  number followed by the six transform numbers). Every section number must exist in
  the series; the translation terms are interpreted in pixels and scaled by the
  section magnification. The imported transforms are written to a new alignment
  named after the file (with the date appended), and the series switches to it.
- **SWiFT project** — import transforms from an AlignEM-SWiFT project; you choose
  the scale to import. The number of transforms must match the number of sections.

Transforms can also be imported from another series via **Series ▸ Import ▸ from
series…** (an Alignments tab lets you pick which alignments to bring over).

### Locking sections

A locked section's transform can't be changed by any means (manual edit, nudges,
estimate/correlate, or propagation), and locked sections are protected from
brightness/contrast changes, thickness edits, image-source edits, and deletion.
Lock/unlock from the **Section list** (the **Locked** column or its
context menu); unlock the current section quickly with **Alignments ▸ Unlock
current section** (`Ctrl+Shift+U`).

---

## 11. 3D reconstruction

### Generating a 3D object

From the **Object list**, select one or more objects and choose **3D ▸ Add to
scene** from the context menu (or **Shift+double-click** an object). The first time,
this opens the 3D scene window; if a scene is already open, the objects are added
to it. Meshes are built on a background thread (you'll see a "Generating 3D…"
progress indicator). Z-traces can also be added to the scene (as tubes) from the
z-trace list.

> 📸 *Screenshot: the 3D scene window with a few reconstructed objects and the scale cube.*

### 3D model types

Each object has a **3D type** (set in **Edit 3D settings…** from the object list):

- **Surface** (default) — a smoothed surface reconstructed from the object's traces
  (negative traces are subtracted, e.g. to hollow out a structure).
- **Spheres** — one sphere per trace, sized to the trace's radius (good for
  point-like or stamped objects).
- **Contours** — each trace rendered as a thin slab, showing the raw cross-sections.

Z-traces render as tubes. **Edit 3D settings…** also sets per-object **opacity**.

Series-wide 3D quality is controlled in **Series ▸ Options** (the 3D section): an
**XY Resolution** slider (less detail/faster ↔ more detail/slower), the **3D
smoothing** method (Humphrey — recommended — Mutable Diffusion Laplacian, Taubin, or
None), the **smoothing iterations**, and the **screenshot resolution (dpi)**.

### Navigating the 3D scene

- **Left-drag** — rotate; **middle-drag** — pan; **right-drag** — zoom. (`Ctrl`-drag
  also rotates.)
- **Double-click** an object — jump the 2D field to that point on the corresponding
  section.
- Click meshes to select them. With objects selected: arrow keys translate in X/Y,
  `Ctrl`+Up/Down translates in Z, `Shift`+arrows and `Ctrl+Shift`+Up/Down rotate.
  `Delete`/`Backspace` removes selected objects from the scene; `[` / `]` step their
  opacity.
- Set the camera along an axis with **X** / **Y** / **Z**, fit everything with
  **Home** ("Focus on all"), and center on the selection with **F**.
- Press **`?`** in the scene for its full shortcut list.

The 3D window has its own menu bar:

- **Scale cube** — toggle a reference cube with the **C** key (or **Scale Cube ▸
  Display in scene**). To move it, select it (left-click) and use the arrow keys
  (X/Y) and `Ctrl`+Up/Down (Z). Edit its **edge length (µm)**, color, opacity, and
  outline width via **Edit ▸ Edit attributes…** (`Ctrl+E`) — it's a physical
  measuring reference.
- **Scene ▸ Change background** — set the background color.
- **Scene ▸ Organize scene…** (`Ctrl+Shift+H`) — line objects up side by side, by
  host group or individually.
- **Scene ▸ Set translate/rotate step…** — the movement increments (default 0.1 µm
  and 10°).
- **File ▸ Save scene… / Load scene…** — save the scene (objects, colors, camera) to
  a JSON file and reload it later (also **Series ▸ 3D ▸ Load 3D scene…** from the
  main window). **Add to scene** can also pull objects from another series.

### Saving images and exporting meshes

- **Scene ▸ Save scene screenshot…** — save a rendered image (PNG, JPG, TIF, or BMP)
  at the configured DPI.
- **Scene ▸ Export scene…** — export the whole scene as a single Wavefront `.obj`
  (with a `.mtl` material file).
- From the **Object list ▸ 3D ▸ Export mesh as** — export individual objects as
  **Wavefront (.obj)**, **OFF (.off)**, **Stanford PLY (.ply)**, **STL (.stl)**, or
  **Collada (.dae)**. (Surface and Spheres objects export; contour and tube types do
  not. Collada export additionally requires the optional `pycollada` package; if it
  is missing you'll be told, rather than seeing an error.)
- **Object list ▸ 3D ▸ Export quantitative data** — write per-object surface area
  and volume to CSV. (Note these depend on the meshing settings; verify mesh quality
  before relying on the numbers.)

---

## 12. Saving and backups

### Saving

**File ▸ Save** (`Ctrl+S`) writes the series back to its `.jser`. **File ▸ Save
as…** writes a copy to a new location. PyReconstruct does **not** auto-save on a
timer, so save regularly. (If you close with unsaved changes, you are prompted to
save; and if a session ends uncleanly, reopening offers to recover it — see
[Opening and creating a series](#4-opening-and-creating-a-series).)

### Backups

A backup is a complete copy of the series saved as an ordinary `.jser` into a
folder you choose, with a filename you configure. There are two ways to make one:

- **File ▸ Backup ▸ Backup now…** (`Ctrl+Shift+B`) — save the current data and write
  a backup, optionally with a comment appended to the filename.
- **Automatic backups** — enable **Auto-backup (create backup on every save)** in
  the backup settings, and a backup is written every time you Save or Save As.

**File ▸ Backup ▸ Settings…** configures the **Backup Folder** and the filename
template, assembled from optional parts — a prefix, the series code, the series
name, the date and time (with customizable strftime patterns), the username, and a
suffix — joined by a delimiter. A live preview shows the resulting filename, and
name collisions get a numeric suffix (`-01`, `-02`, …). The folder and the
auto-backup toggle are remembered **per series**; the naming template is shared
across all series. (The backup folder and naming are also available under **Series ▸
Options ▸ Backup**.)

> 📸 *Screenshot: the Backup Settings dialog showing the folder, the auto-backup checkbox, and the filename preview.*

Because backups are just `.jser` files, **restore a backup by opening it** with
**File ▸ Open**. If the configured backup folder is missing at save time (for
example a disconnected network drive), PyReconstruct prompts you to set it, or
disables auto-backup until you do.

> **Tip.** Keep your backup folder on separate storage from your working `.jser`,
> and turn on auto-backup for active projects.

---

## 13. Keyboard shortcuts

These are the defaults; rebind them under **Help ▸ Shortcuts list** (`?`).

### Tools

| Key | Tool |
|---|---|
| `P` | Pointer |
| `Z` | Pan/Zoom |
| `K` | Knife |
| `C` | Closed Trace |
| `O` | Open Trace |
| `S` | Stamp |
| `G` | Grid |
| `F` | Flag |
| `Q` | Host |

(Scissors and the Z-trace tool are selected from the palette.)

### Files and series

| Key | Action |
|---|---|
| `Ctrl+N` | New series from images |
| `Ctrl+O` | Open series |
| `Ctrl+S` | Save |
| `Ctrl+Shift+B` | Backup now |
| `Ctrl+R` | Reload |
| `Ctrl+Q` | Quit |
| `Shift+O` | Series options |

### Sections and view

| Key | Action |
|---|---|
| `PgUp` / `PgDown` | Next / previous section |
| `Ctrl+G` | Go to section |
| `/` | Flicker between two sections |
| `Home` | Fit view to image |
| `Space` | Blend current and last section |
| `Shift+F` | Find contour on this section |
| `Ctrl+F` | Find an object's first contour |

### Editing traces

| Key | Action |
|---|---|
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+X` / `Ctrl+C` / `Ctrl+V` | Cut / Copy / Paste |
| `Ctrl+B` | Paste attributes |
| `Ctrl+E` | Edit trace attributes |
| `Ctrl+M` | Merge traces |
| `Ctrl+H` / `Ctrl+U` | Hide selected / Unhide all |
| `Ctrl+A` / `Ctrl+D` | Select all / Deselect |
| `H` / `A` | Hide trace layer / Show all traces (ignore hidden) |
| `I` | Hide image |
| `Space` | Section blend |
| `X` | Focus mode |
| `Delete` / `Backspace` | Delete selected (or remove last point while tracing) |

### Lists and alignment

| Key | Action |
|---|---|
| `Ctrl+Shift+O` | Object list |
| `Ctrl+Shift+T` | Trace list |
| `Ctrl+Shift+S` | Section list |
| `Ctrl+Shift+Z` | Z-trace list |
| `Ctrl+Shift+F` | Flag list |
| `Ctrl+Shift+A` | Modify / switch alignments |
| `Ctrl+T` | Edit current section transform |
| `Ctrl+Shift+U` | Unlock current section |
| `Ctrl+\` | Align by correlation |

For the complete, current list (including 3D-scene shortcuts and palette
shortcuts), open **Help ▸ Shortcuts list**.

---

## 14. Getting help

In the app, **Help ▸ Online resources** links to:

- the [PyReconstruct user guide](https://wikis.utexas.edu/display/khlab/PyReconstruct+user+guide)
  on the UT Austin lab wiki,
- this distribution's [source code](https://github.com/dustenhubbard/PyReconstruct),
- the [Kristen Harris Lab website](https://synapseweb.clm.utexas.edu/harrislab) and
  the [Atlas of Ultrastructural Neurocytology](https://synapseweb.clm.utexas.edu/atlas).

Found a bug, have a feature idea, or want to improve the docs? Please open an issue
on this distribution's
**[GitHub Issues](https://github.com/dustenhubbard/PyReconstruct/issues)**, which you
can also reach from the in-app **Help ▸ Report issues (GitHub)** menu. When reporting
a bug, include the version/commit shown at the top of the **Help** menu (clicking it
copies the commit to your clipboard).

---

## Credits

PyReconstruct was created by Michael A. Chirillo, Julian N. Falco, Michael D.
Musslewhite, Larry F. Lindsey, and Kristen M. Harris (Kristen Harris Lab,
Department of Neuroscience, Center for Learning and Memory, **The University of
Texas at Austin**) and introduced in *PNAS* (2025). The upstream project lives at
[SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct); it succeeds
the original **Reconstruct** by John C. Fiala.

This distribution is independently developed and maintained by **Dusten Hubbard**
(Kristen Harris Lab, **The University of Texas at Austin**). See the
[README](../README.md) for provenance, performance notes, and citation details, and
[CONTRIBUTING.md](../CONTRIBUTING.md) to help improve PyReconstruct.

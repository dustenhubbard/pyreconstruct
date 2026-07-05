# The Tool Palette

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
them by right-clicking that button — see [The trace palette](The-Trace-Palette)).

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
**Resolved**. All flags in the series are listed in the [Flag list](Data-Lists).

### Host (`Q`)

Sets host (parent) relationships between objects. **Click a first trace** (the
object that will be hosted), then **click a second trace** (its host); a line is
drawn between them while you choose. **Right-click** to cancel. An object can't host
itself, and two objects can't host each other. Hosts also appear as a column in the
object list and can be set from the object list's context menu.

### Z-trace tool

Creates a [z-trace](Core-Concepts) — a curve through the stack. Select the
tool, then **click** points (changing sections between clicks as needed with the
mouse wheel); **right-click to finish**. The new z-trace takes the current
preset's name and color. (This tool is selected from the palette; it has no default
keyboard shortcut.)

---
‹ [The Main Window and Navigation](The-Main-Window-and-Navigation) · [Home](Home) · [The Trace Palette](The-Trace-Palette) ›

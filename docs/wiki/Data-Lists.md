# Data Lists

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
‹ [Working with Traces](Working-with-Traces) · [Home](Home) · [Alignment](Alignment) ›

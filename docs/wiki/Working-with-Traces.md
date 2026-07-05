# Working with Traces

Most trace editing is on the **field context menu** (right-click selected traces),
with keyboard shortcuts for the common actions. Selected-trace actions affect *all*
selected traces.

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
- **Toggle hide all** (`H`) and **Toggle show all** (`A`) — temporarily hide or
  show every trace regardless of individual hidden state (the field border turns
  red when all are force-hidden, green when all are force-shown). These differ from
  per-trace Hide/Unhide.
- **Blend** (`Space`) — blend the current and last-viewed section, to compare them.
- **Toggle hide images** (`I`), **Focus mode** (`X`).

**Undo** (`Ctrl+Z`) / **Redo** (`Ctrl+Y`) cover actions on the field. (Some edits
made through the lists are noted there as not undoable.)

**Find a contour** on the current section with **Section ▸ Find contour…**
(`Shift+F`); jump to an object's first contour anywhere in the series with
**Series ▸ Find first object contour…** (`Ctrl+F`).

---
‹ [The Trace Palette](The-Trace-Palette) · [Home](Home) · [Data Lists](Data-Lists) ›

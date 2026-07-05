# Alignment

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
- **Alignments ▸ Modify alignments** (`Ctrl+Shift+A`) opens the alignment dialog,
  where you can create a **New** alignment (created as a copy of the current one),
  **Rename**, or **Remove** alignments. Objects can also carry a per-object
  alignment override (**Change object alignment…** in the object list).

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
‹ [Data Lists](Data-Lists) · [Home](Home) · [3D Reconstruction](3D-Reconstruction) ›

# 3D Reconstruction

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
- From the **Object list ▸ 3D ▸ Export meshes** — export individual objects as
  **Wavefront (.obj)**, **OFF (.off)**, **Stanford PLY (.ply)**, **STL (.stl)**, or
  **Collada (.dae)**. (Surface and Spheres objects export; contour and tube types do
  not.)
- **Object list ▸ 3D ▸ Export quantitative data** — write per-object surface area
  and volume to CSV. (Note these depend on the meshing settings; verify mesh quality
  before relying on the numbers.)

---
‹ [Alignment](Alignment) · [Home](Home) · [Saving and Backups](Saving-and-Backups) ›

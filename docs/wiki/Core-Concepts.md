# Core Concepts

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
  [Alignment](Alignment).)
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
[Opening and creating a series](Opening-and-Creating-a-Series)).

---
‹ [Keeping PyReconstruct Up to Date](Keeping-PyReconstruct-Up-to-Date) · [Home](Home) · [Opening and Creating a Series](Opening-and-Creating-a-Series) ›

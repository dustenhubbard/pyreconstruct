# Opening and Creating a Series

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
‹ [Core Concepts](Core-Concepts) · [Home](Home) · [The Main Window and Navigation](The-Main-Window-and-Navigation) ›

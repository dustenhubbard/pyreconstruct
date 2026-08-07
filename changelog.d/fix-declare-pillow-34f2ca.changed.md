- **Pillow is now a declared dependency instead of one the install happened to
  pick up.** `modules/backend/exports/svg_conversion.py` does
  `from PIL import Image` inside `export_svg` -- it is how the section image
  becomes the base64 PNG embedded in the exported SVG, and therefore how PNG
  export gets its input too -- but pillow was named in no dependency file. This
  fixed nothing you could see: pillow was installed in every environment
  anyway, arriving behind five other packages (`cairosvg` and `scikit-image`
  directly, `imageio` behind `scikit-image`, `matplotlib` behind `vtk`, and
  `neuroglancer` behind a developer-only extra). The export worked, and it works
  the same now.

  What changes is that it no longer depends on those five. Each of those edges
  belongs to another project and can be withdrawn by a version bump nobody here
  makes deliberately, and the failure that would follow is worse than the
  equivalent for `svgwrite` and `cairosvg` was: the `modules_available` guard in
  front of `File > Export > SVG` and `File > Export > PNG` probes those two and
  does not probe `PIL`, so it would report the feature as available and the
  export would then raise an uncaught `ModuleNotFoundError` -- a crash report,
  not the guard's offer to install the missing package.

  `pillow==12.3.0` is added to `pyproject.toml`, `requirements.txt` and
  `uv.lock`. It is the version already resolved, so nothing installs, upgrades
  or downgrades as a result; the lock gains two lines and re-resolves nothing.
  `tests/test_export_svg_png.py` gains the declaration and importability checks
  for it, a check that decodes the exported SVG's embedded image and reads its
  PNG header (so pillow's contribution is asserted on its output, not on the
  package being importable), and one that injects a missing pillow to pin the
  guard's blind spot described above.

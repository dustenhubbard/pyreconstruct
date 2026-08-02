- **Fixed: Reset Defaults now moves the sliders in `Series ▸ Options`.** The
  dialog rebuilds itself with `use_defaults=True` when Reset Defaults is
  pressed, and an option that passes that flag to
  `series.getOption(name, use_defaults)` comes back at the shipped default.
  Three sliders did not pass it: 3D XY resolution, scale bar size and CPU
  usage. They read the stored value unconditionally, so those three stayed
  exactly where the user had left them. Six non-slider options in the same
  dialog share the same cause and are not covered here.

  Also guards `determine_cpus` against `os.cpu_count()` returning `None`, which
  Python documents as possible. The dialog does not call it; its only caller is
  the image-to-zarr conversion, which is where a `None` would otherwise raise.

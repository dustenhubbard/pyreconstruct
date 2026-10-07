- **Export to XML writes a fill condition of `none` the way PyReconstruct draws
  it.** A filled trace whose condition is `none` is filled when unselected, but
  the export wrote it as filled when selected, so after an import its fill
  appeared only when selected. It now exports as filled when unselected.

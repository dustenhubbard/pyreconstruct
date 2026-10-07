- **Export to XML writes a fill condition of `none` the way PyReconstruct draws
  it.** A filled trace with that condition is filled when unselected, but the
  export wrote it as filled when selected, so it came back the other way around
  after an import.

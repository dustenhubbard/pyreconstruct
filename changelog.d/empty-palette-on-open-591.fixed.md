- **A series saved with an empty palette opens and works again.** An older
  palette CSV import could save a palette with no buttons, and showing it
  crashed PyReconstruct. Empty palettes are now dropped when a series opens,
  and `Edit all palettes...` refuses to save one.

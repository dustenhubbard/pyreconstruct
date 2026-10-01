- **Loading a 3D scene with missing objects names them all.** A scene that
  named two objects the series no longer has raised `IndexError` when loaded,
  and with some of its objects still there the prompt named the wrong ones.
  PyReconstruct now lists every missing object and goes on with the rest if you
  say yes.

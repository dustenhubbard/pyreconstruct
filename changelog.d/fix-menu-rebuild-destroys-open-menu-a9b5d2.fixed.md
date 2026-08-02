- **The flag list's "Display resolved flags" and the object list's categorical
  column filters no longer raise an error on the first click.** Both rows
  rebuild the list from inside their own handler, and rebuilding the list
  rebuilds the menubar the row lives in. That rebuild started with
  `menubar.clear()`, which drops the menubar's claim on that generation of
  menus and actions while the list widget is still holding them, both in its
  own action list and in the `<name>_act` attributes the menu builder sets. The
  next build's "remove previous action" step then reached one of those dead
  objects and raised `RuntimeError: Internal C++ object (PySide6.QtGui.QAction)
  already deleted`, so the click produced an error dialog and a half-built
  menubar instead of a filtered list. The rebuild now releases the previous
  generation first, while it is still alive, and only then clears. Every
  menubar that is rebuilt in place goes through the same path, so the object,
  trace, ztrace, section and flag lists and the main window are all covered.

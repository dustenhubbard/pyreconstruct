- **`Ctrl+Shift+H` now runs `Set hosts...`, which it never did from a fresh
  install.** The action carried a default key in `default_settings.py` and an
  editable row in the shortcuts dialog, but the object menu built it with `""`
  as its shortcut, and only that third argument binds anything. The key was
  therefore dead out of the box. It went unreported because opening
  `Shortcuts...` and pressing OK repaired it in passing: `resetShortcuts` writes
  onto the QAction the menu already built, so anyone who went looking at the
  list fixed their own copy and could not reproduce it afterwards, until the
  next context-menu rebuild re-applied the `""`. The menu now passes the series,
  so the key resolves by action name like every other configurable shortcut.

- **`Ctrl+Shift+D` runs `Add to 3D scene` again while the object list is open.**
  The object list is a dock inside the main window and builds its right-click
  menu from the same definition the field uses, so every keyed row of that menu
  was constructed twice in one window. Qt answers two actions claiming one key
  sequence with `Ambiguous shortcut overload` and fires neither, so opening the
  list killed the key and closing it brought the key back. The list's copy is
  now built without the keys, the rule the trace list already followed, and the
  field's copy keeps them. That copy is scoped to the whole window, the docked
  list included, so both object menu keys now work wherever the focus sits.

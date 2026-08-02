- **A checkable menu item no longer closes its menu, so a set of toggles can be
  set in one trip.** Turning on the trace palette, the section increment buttons
  and the scale bar under `View > Palette > Visibility` meant walking three menus
  down, clicking once, and starting the descent again, three times over. The
  field's right-click `View` group was worse, because getting a dismissed context
  menu back costs another right-click, and its five rows (focus mode, hide trace
  layer, show all traces, hide image, section blend) are routinely set in
  combination. Qt closes a menu on any activation and draws no distinction
  between a command and a toggle, so the distinction is now drawn where menu
  items are built: a click on a checkable row toggles it in place and leaves the
  menu standing, while a plain row still runs and closes as before. Esc, clicking
  away, and every keyboard shortcut are unchanged, and nothing in either menu
  moved, was renamed, or was added. Every toggle the shared menu builder makes
  gets this, so it also covers the group visibility list, the object list's
  column filters, the flag list's "Display resolved flags", and the 3D scene's
  two toggles.

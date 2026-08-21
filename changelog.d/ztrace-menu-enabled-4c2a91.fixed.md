- **Fixed the z-trace commands being greyed out almost all the time.** The
  Z-trace submenu holds nine commands, and every one was disabled unless the
  right-click landed on an already-selected z-trace with no trace selected
  alongside it, so the menu read as empty rather than as unavailable. Two rules
  produced that: selecting both a trace and a z-trace switched off both menus,
  and the gate asked what was under the cursor. No z-trace command reads what
  was clicked. They all act on the selection, so the selection is what decides
  now.

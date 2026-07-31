- **The object right-click menu is reordered so Add to 3D scene sits directly
  above the 3D ▸ submenu it belongs to.** The two were fifteen rows apart, with
  the whole visibility family, Group ▸ and Set curation ▸ between them, so the
  pair read as two unrelated entries and finding one gave no hint where the
  other was. They are now adjacent, and the rest of the menu falls into three
  sections behind them: the visibility family unchanged, then the per-object
  settings (Comment..., Duplicate object, Group ▸, Set curation ▸, Custom
  categories ▸, Object attributes ▸ and Geometry ▸) collected in one place, then
  the tail ending in Delete objects. Nothing was renamed, added or removed, and
  every action keeps the submenu it lived in. One builder backs both surfaces,
  so the object list's menu and the field menu's Object ▸ submenu change
  together.

- **Add to 3D scene is offered inside 3D ▸ as well as at the top level.**
  Hoisting it out of the submenu entirely made it harder to find, not easier:
  3D ▸ held only Remove from scene, so anyone who opened the submenu looking for
  "add" came away empty and went hunting. It now appears in both places, the way
  Edit object attributes... already does. Only the top-level copy carries the
  keyboard shortcut, because two actions sharing one sequence is an ambiguous
  binding and Qt answers an ambiguous shortcut by firing neither action.

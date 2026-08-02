- **Setting an object's comment, curation, last user or alignment from a script
  now takes effect.** `series.objects["name"]` is the documented way to reach an
  object's attributes without the interface, and four of its setters quietly did
  nothing. Assigning to any of them appeared to succeed and left the series
  exactly as it was, so a script that stamped a comment across a hundred objects
  finished with no error and no comments. Nothing in the interface assigns
  through these setters, so nothing a user does through the windows and menus
  was affected.

  Each of the four called `getAttr` where it meant `setAttr`. The two take
  different arguments, so the value being assigned landed in `getAttr`'s
  `ztrace` flag, where all it did was pick which table to read from, and the
  result was thrown away. The value was never stored anywhere. Reading the
  attribute back through the same property returned the old value, since the
  getters were right all along.

  Reading `opacity_3D` from the same accessor returned the object's 3D mode
  instead of its opacity, a string such as `surface` where a number between 0
  and 1 was expected. The property was built from the wrong decorator, which
  gave it the neighboring `mode_3D` property's read half and discarded its own.
  Writing to it always worked and still does, and `mode_3D` itself was correct
  in both directions.

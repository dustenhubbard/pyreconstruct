- **The lint gate now catches unused imports and redefined names (`F401`,
  `F811`).** The gate selected the critical-error set only, so an import left
  behind by a deleted call site, or a second definition silently overwriting the
  first, merged without comment. Enabling the two rules needed a cleanup pass
  first: 484 findings, of which 352 are deliberate re-exports and 128 are
  genuinely dead. The re-exports are why this was not a `--fix`. A module that
  exists to re-export imports names it does not itself use, so pyflakes calls all
  352 unused while runtime depends on every one of them; deleting them would have
  left the gate green and the application unable to start. They are covered by
  `per-file-ignores` instead, for `**/__init__.py` and for `main_imports.py`,
  which `main_window.py` reads through `import *`. The 128 dead imports are
  removed, 58 of them function-local. Every one of the 174 package modules was
  imported directly afterwards to show no re-export chain broke, which the suite
  alone would not have shown.

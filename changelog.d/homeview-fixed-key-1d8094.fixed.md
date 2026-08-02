- **Rebinding `Home` in the shortcuts list now sticks instead of reverting on
  the next series open.** `Home` (`View ▸ Set view to image`) has a default in
  `default_settings.py` and an editable field in `Help ▸ Shortcuts list`, but
  its menu entry in `menubar.py` carried the literal key rather than reading the
  setting, so `createMenuBar` put `Home` back every time a series was opened.
  The menu entry now reads the setting, like the other configurable shortcuts.

  Moving `Home` to another command used to cost you both keys. The dialog
  releases `Home` once its own row gives it up, so it accepted the reassignment,
  and then the next series open restored `Home` on `View ▸ Set view to image` as
  well. Two actions holding one sequence means neither fires. Both keys now do
  what they were set to.

  `Home` is no longer listed as a fixed shortcut in the user guide. `PgUp`,
  `PgDown`, `Ctrl+\` and `?` are still fixed.

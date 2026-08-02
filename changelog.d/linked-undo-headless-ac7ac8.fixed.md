- **Undo no longer stalls with no user present when the action spanned several
  sections.** When both a series-wide undo and a section-only undo are
  available and linked, `MainWindow.undo` asks whether to undo all sections or
  only the open one. The prompt was a `QMessageBox` constructed inside the
  method, which with no window manager to dismiss it spins a modal event loop
  that never returns, so `undo()` hung outright in any headless run. It is now
  `linkedUndoNotify` in `gui/utils/utils.py`, guarded by `user_is_present()`
  alongside `saveNotify` and `unsavedNotify`, and answers "all sections" when
  nobody can be asked. The dialog is unchanged for anyone running the app.
  Adds `tests/test_linked_undo_headless.py`, which deletes an object from the
  series and drives all three answers through the real `undo()`. Those tests
  could not have been written before: the prompt was the one shape the test
  fixture could not reach, since it replaces module-level names and the
  `QMessageBox` statics and this was neither.

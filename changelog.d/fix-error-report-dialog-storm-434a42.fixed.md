- **An error that keeps happening now opens one window instead of an endless
  stream of them.** The exception hook opened an error window per occurrence,
  which is fine for a failure the user can stop provoking and a trap for one they
  cannot. An exception raised while a widget paints recurs on every repaint, and
  a repaint is not something a user can decline: the window's own event loop
  delivered the next paint event, which raised, which opened another window on
  top; and closing one exposed the widget underneath, which repainted, which
  raised again. Reported on 1.21.0 as "a neverending stream of these windows and
  I can't close them", with Task Manager the only way out. A report can no longer
  open from inside another one's window, and a fault -- identified by its type
  and the line that raised it -- opens a window once per session. A second,
  unrelated error that happens while a window is up is held back rather than
  spent: it does not stack on top, and it still gets its own window the next time
  it occurs with nothing in the way. Every occurrence is still written to the log
  file, so nothing is lost: `Help > View log file` shows the repeats, and the
  window now says so.

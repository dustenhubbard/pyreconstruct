- **Progress dialogs appear immediately.** Removed the delay before shared
  progress dialogs open, so commands show feedback before processing their
  first item. Transform propagation also reports progress while checking
  sections, before asking about locked sections or applying the alignment.
  Repeated completion updates no longer reopen a finished progress dialog.
  Section lists retain keyboard focus, and progress opened after a series
  closes no longer attaches to its closed window.

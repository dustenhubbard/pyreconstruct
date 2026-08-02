- **The flag list's `Filter ▸ Display resolved flags` turns back off, and shows
  a checkmark while it is on.** Toggling the row rebuilds the flag list's whole
  menubar, and the row was built from a constant unchecked checkbox rather than
  from the filter's current state. The rebuilt row therefore lost the checkmark,
  and the handler, which read that freshly unchecked row back, saw "on" every
  time: resolved flags could be switched into the list and never out of it. The
  row is now built from the filter's state and the handler flips that state
  directly, the way the object list's categorical column filters already do.

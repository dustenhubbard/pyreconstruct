- **Flags saved before flags had IDs keep the same identity every time the file
  is opened, so importing them from a colleague's copy merges them instead of
  duplicating them.** A flag stored in the older format carries no ID, and the
  format upgrade that runs on every open invented a random one. Nothing
  compares flags by name or position: `Flag.equals` compares IDs and nothing
  else, and importing flags from another series deduplicates entirely through
  it. Two people who each opened the same older series and saved it therefore
  held the same flag under two IDs, and importing one into the other stacked a
  second copy on top of every one of those flags, matching in name, position
  and comments. The ID is now derived from the flag's own content, so it comes
  out the same in every copy of the file and on every open, including a file
  that is only ever read. Flags that already carry an ID are untouched, and a
  derived ID is six characters from the same alphabet as a newly created one,
  so nothing can tell the two apart.

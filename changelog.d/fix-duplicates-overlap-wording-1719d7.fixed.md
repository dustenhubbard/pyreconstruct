- **The `?` help in `Series ▸ Clean up ▸ Duplicates...` no longer overstates
  how alike a row's traces are.** A row joins traces in a chain, so when A
  overlaps B and B overlaps C, A and C can overlap less than the Overlap column
  shows. The help now says the number is the lowest of the pairs that put the
  traces in one row. When a locked object stops a row from combining, the
  notice suggests keeping its name only when that would work, and otherwise
  says to unlock it.

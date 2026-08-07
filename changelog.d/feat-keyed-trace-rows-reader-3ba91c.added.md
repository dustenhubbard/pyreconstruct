- **A trace row in a `.jser` may now carry the trace's own id, and opening the file
  keeps it.** The keyed row shape -- a JSON object per trace instead of an
  8-element array -- has been readable since before `v1.19.0`, but the `id` on
  such a row was silently discarded and the trace was given a fresh id derived
  from its content instead. It is adopted now, so an id written into a file is the
  id the trace has when the file is opened again, on this machine or anyone
  else's. Both spellings of the fill-mode key are accepted (`fill_mode` and the
  legacy `mode`), and a row that carries no id still derives one exactly as
  before, so every file that exists today loads unchanged. The id was found to be
  destroyed one layer higher than expected -- `Series.openJser` migrates each
  section into its hidden working directory and the object model reads that copy,
  never the `.jser`, so the conversion to the positional shape deleted the id
  before the load path could ever see it. The working copy now keeps the id, and
  keeps it under the same key spelling the source file used, so the section stays
  readable by exactly the builds that could read it before.
- **Two traces claiming the same id are reported instead of quietly accepted.** The
  first claim wins, the second is refused and recorded against the object's name,
  and that trace gets an id of its own rather than a copy of somebody else's --
  which is the failure mode that makes a merge lose an edit. An id in a file that
  is not a readable id at all is likewise refused and recorded rather than raised,
  so one hand-edited row cannot turn a whole series into a file that will not
  open.
- **Undo no longer silently corrupts a section whose file uses keyed rows.** The
  undo baseline is a byte copy of the section file, parsed without the migration
  every other reader goes through, and handed a keyed row it did not fail --
  Python reports a dict's length as its key count and iterates it as its keys, so
  the baseline became a trace named `x` whose points were pairs of JSON key names.
  The first undo restored that over the user's real traces. The baseline reader
  understands the keyed shape now.

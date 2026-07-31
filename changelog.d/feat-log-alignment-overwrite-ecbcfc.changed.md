- **Importing an alignment over one that already exists is now recorded in the
  log as an update rather than as an import.** Replacing a same-named alignment
  already worked, and `Alignments > Import alignments` already names the
  alignments about to be replaced and asks before doing it, but the log said the
  same thing either way: one `Import alignments <names> from another series`
  line, whether the names were new or were overwriting a colleague's earlier work
  on every section in the series. An alignment quietly replaced everywhere is the
  change a reader of the log most needs to find. `Series.importTransforms` now
  splits the names it was handed into those the series did not have and those it
  did, reading that split before it starts saving sections, and logs
  `Import alignments ...` and `Update alignments ...` separately. Both lines name
  the alignment as it exists in this series, so an alignment renamed on the way in
  is logged under the name it was given rather than the name it had in the other
  series; on an import that does not rename, which is the default, the line reads
  exactly as it did before.

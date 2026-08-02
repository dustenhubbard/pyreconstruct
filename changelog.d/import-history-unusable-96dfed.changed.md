- **An import that cannot use the history check now says so before it runs.**
  "Check history" in `Series ▸ Import series data ▸ From another series` compares
  the two series' logs and keeps their longest matching opening run as the point
  the copies diverged. That is what lets the import honor a deletion or a rename
  instead of reading the missing object as something the other person has not
  drawn yet. When the two logs have no matching opening run, there is no
  divergence point to measure against, the whole history step is skipped, and the
  import goes ahead as a plain merge of both series. Nothing said so: no message,
  no log line, and the box stayed checked. An empty log on either side is enough
  to reach it, and a series converted from another format starts with one, as
  does a series whose log was exported and trimmed on one side only.

  Measured on the series that ships with this repository, whose log is empty:
  copy it, delete an object in the copy, then import the original back with the
  history check on, and the deleted object is present again afterwards. The
  import now names the reason the check cannot be used, says that deletions can
  come back and renames can land under both names, and asks whether to continue.
  Answering no leaves the series exactly as it was. The merge itself is
  unchanged.

- **Auto-merge now works the same in polygon mode as in pencil mode.** The
  auto-merge option merged whenever two or more selected closed traces shared
  the new trace's name, without ever testing whether they touched. Whether the
  pre-existing trace happened to be selected differs between the two tracing
  gestures, so a closed polygon trace often refused to merge where a pencil
  trace merged, and two selected same-name traces drawn far apart merged when
  neither should have. Finishing a closed trace now merges it with every
  same-name closed trace on the section that actually overlaps it, selected or
  not, and leaves non-overlapping ones alone, so drawing traces apart is still
  the way to keep separate traces under one name. The merged trace keeps the
  existing trace's color and tags rather than the palette's fresh copy.

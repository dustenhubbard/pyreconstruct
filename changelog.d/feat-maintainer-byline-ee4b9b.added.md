- **The release notes now carry a maintainer byline.** The "What's new" dialog
  renders it once below the notes, set off by a rule, on every framing (an
  update, a fresh install, the Help menu re-open, and the generic fallback), and
  the GitHub release body prints it near the developer-changelog footer. The line
  reads "An independent build of PyReconstruct, maintained by Dusten Hubbard." so
  a lab that installs a build knows whose it is and reports its issues to the
  right person. It comes from a single `MAINTAINER_BYLINE` field on the notes
  builder, so the two surfaces cannot drift apart.

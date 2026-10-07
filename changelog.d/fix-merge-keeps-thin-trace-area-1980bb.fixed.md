- **Merging no longer deletes most of a very thin trace.** A sliver thinner
  than a quarter of an image pixel closed up into a line when the merged
  outline was simplified, so the merge kept almost none of its area. If the
  merged outline would keep less than half of any trace, every trace is now
  left as it was.

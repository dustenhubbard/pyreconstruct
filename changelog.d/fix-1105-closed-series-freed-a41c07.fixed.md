- **Opening another series frees the memory of the one that was open.** The
  first series opened in a session stayed in memory until PyReconstruct quit,
  so a second open of a large series could double its memory use.

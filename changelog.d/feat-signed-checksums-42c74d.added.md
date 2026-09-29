- **PyReconstruct checks each update's signature before installing it.** Every
  release now carries a signed list of checksums, and PyReconstruct refuses a
  download that is missing from that list or whose signature does not match.

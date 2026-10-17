- **Opening a large series takes far less memory.** The file is now read one
  section at a time instead of all at once, so a 1.4 GB series peaks at about
  2.5 GB while it opens instead of 10.3 GB. The file format is unchanged. If
  an open stops partway and PyReconstruct cannot put back the hidden folder
  beside the file, it says where that folder's files are, and later opens name
  that folder too.

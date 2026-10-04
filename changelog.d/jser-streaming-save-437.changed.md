- **Saving a large series needs far less memory.** PyReconstruct used to read
  every section into memory and build the whole file before writing it. It now
  writes the file one section at a time, and the saved file is exactly the same
  as before.

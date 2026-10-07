- **`Save as...` refuses a name that differs only in case on an empty mounted
  drive.** To tell whether `b.jser` is the same file as a deleted `B.jser` with
  objects in the 3D scene, PyReconstruct judged the empty drive by the folder it
  is mounted in. A drive that ignores case, mounted in a folder that does not,
  let the save through. It now refuses when it cannot tell.

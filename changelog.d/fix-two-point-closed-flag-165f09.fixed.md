- **A two-point trace's `closed` flag is now corrected in the saved file, not
  only in memory.** Two points enclose no area, so every reader already forced
  such a trace open once it was loaded, but the stored flag was left alone. The
  file therefore kept a value the program contradicted, and it did not keep it
  consistently: a series opened and saved without visiting that section
  round-tripped the stale `true` unchanged, while the first save that took the
  section back through the model wrote `false`. The flag flipped at an
  unpredictable later save rather than never, so a byte-level diff of a `.jser`
  in version control showed a change no edit accounted for. The correction now
  happens once, when the `.jser` is unpacked, alongside the existing removal of
  traces with fewer than two points. A Reconstruct XML import was the in-app
  source of such rows, since it writes the contour's stored flag through without
  checking how many points it has.

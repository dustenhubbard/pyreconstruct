- **The CPU usage slider stops at the worker count that is actually fastest.**
  The setting is a share of your cores, and the top of it used to buy
  more workers than the image-to-zarr conversion can use. That was not a plateau
  but a pessimization: measured on a 10-core machine, 8 workers ran **8% slower**
  than 5 while burning **19% more CPU** (14.16 vs 11.93 CPU-seconds). The
  conversion is I/O bound, so past a handful of workers the extra ones only add
  filesystem and metadata pressure, and each one holds a full-resolution tile in
  memory. The ceiling is now 5 workers. The slider keeps its full 0-100% range,
  because the setting is a share of the machine and no single percentage means
  five workers everywhere: on a 4-core laptop nothing changes at all, and on a
  larger machine the top of the range now levels off instead of climbing past the
  useful point. Everything below the ceiling is untouched, the shipped default
  (50%) included.

  **The number next to the slider is honest again at the top of the range.** The
  readout resolved the percentage into workers without applying the converter's
  cap, so on a 10-core machine it read `100% (10 of 10 workers)` while the
  conversion started 8 -- the same "believed four, ran eight" surprise the
  readout was added to answer, pointing the other way. It now resolves through
  the cap, so it reads `100% (5 of 10 workers)` and the worker count on the label
  is once again the worker count that starts. The dialog says why going higher
  does not help.

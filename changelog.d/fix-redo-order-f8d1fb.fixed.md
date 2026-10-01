- **Redo replays steps in the right order.** After a series step and then a
  section step were both undone, redo used to replay the section step first,
  and the series step then reverted it. Redo now replays them in the order
  they were made.

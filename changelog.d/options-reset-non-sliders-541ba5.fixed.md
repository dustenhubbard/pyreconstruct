- **`Series > Options`: `Reset Defaults` now resets `trace_mode`,
  `sampling_frame_grid`, `smoothing_iterations`, `screenshot_res`, `theme`,
  and `series_code_pattern` to their shipped defaults.** Six `getOption`
  calls in `createWidgets` did not forward the `use_defaults` flag, so the
  button left those options showing whatever the user had set instead of the
  defaults.

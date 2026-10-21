# Render docs videos from stills

This tool renders an animated step-through from captured images, an authored
cursor, click cues, and camera keyframes. It does not capture continuous footage
or open PyReconstruct. Pillow is already a runtime dependency. FFmpeg with
`libx264` and FFprobe must be on `PATH`, or supplied with `--ffmpeg` and `--ffprobe`.

From the repository root, render a scene:

```sh
uv run --frozen --no-default-groups python dev/docs_media/video/render.py /path/to/scene.json --output /path/to/video-1080p.mp4 --width 1920
```

Use `--width 3840` for 4K. The height follows the scene's aspect ratio. Both output
dimensions must be even. The renderer refuses to overwrite an existing video.
It writes a temporary MP4 beside the destination and publishes it only after a
successful encode. A failed render removes its own temporary files.

Decode the outputs to verify frame counts and generate contact sheets:

```sh
uv run --frozen --no-default-groups python dev/docs_media/video/verify.py /path/to/video-1080p.mp4 /path/to/video-4k.mp4 --output-dir /path/to/review
```

Add `--reference-sheet /path/to/old-contact-sheet.jpg` to generate `comparison.jpg`.
The left panel preserves the old sheet's sampling. The right panel uses the first
video's decoded frames at exactly 0, 1, 2, and subsequent whole seconds.
`verification.json` records dimensions, decoded frame counts, duration, audio
stream count, byte sizes, SHA-256 hashes, and the probe and extraction commands.

Run the synthetic tests, including a short FFmpeg round trip:

```sh
uv run --frozen --no-default-groups --extra test python -m pytest dev/docs_media/video/test_render.py
```

## Scene format

The renderer accepts the original scene format without changes. Times are seconds.
Coordinates use the native image canvas with the origin at the top left, x to the
right, and y down. Image paths resolve relative to the scene file, regardless of
the working directory. Every image must match `size`.

```json
{
  "size": [3840, 2160],
  "duration": 3,
  "cursor_size": 76,
  "images": {"before": "source/before.png", "after": "source/after.png"},
  "states": [
    {"time": 0, "image": "before"},
    {"time": 1.6, "image": "after", "fade": 0.12}
  ],
  "cursor_start": [1800, 1100],
  "moves": [
    {"start": 0.3, "end": 1.3, "to": [2400, 700],
     "controls": [[2000, 1100], [2350, 900]]}
  ],
  "clicks": [1.5],
  "cursor_fade_out": 2.4,
  "camera": [
    {"time": 0, "x": 1920, "y": 1080, "zoom": 1},
    {"time": 0.3, "x": 1920, "y": 1080, "zoom": 1},
    {"time": 1.3, "x": 2400, "y": 800, "zoom": 1.5}
  ]
}
```

- `size` is the native capture width and height. `duration` must span a whole
  number of frames at 60 fps. Frames sample `n / 60`, excluding the end time.
- `states` starts at zero and uses increasing times. An omitted `fade` cuts
  immediately. A fade begins at the state's time and ends after `fade` seconds.
  Fades cannot overlap the next state or run beyond the scene duration.
- Each move follows a cubic Bezier curve from the previous endpoint through two
  absolute control points to `to`. The cursor holds still between moves. Moves
  must be ordered and cannot overlap.
- `clicks` lists increasing cue times. Each pulse remains anchored to the cursor's
  native position at that click. A cue does not change the image automatically.
  Author the corresponding state after the cue.
- Camera keys contain a center and a zoom of at least 1. The crop stays inside
  the source canvas. Duplicate camera values at different times create a hold.
  The last camera key holds until the end. Keep camera motion apart from clicks
  when authoring a flow.
- `cursor_size` is the arrow height at native resolution. It scales with output
  width, independently of camera zoom. Its tip follows the transformed target.
  Optional `cursor_fade_out` starts a 0.4-second fade. When omitted, the cursor
  stays visible to the end.

The original scene does not specify easing or decorative details. This renderer
uses smoothstep easing for moves, camera keys, and state fades, a dark arrow with
a white outline and blurred shadow, and a 0.45-second expanding blue-gray pulse.
These are reconstruction choices, not a pixel-identical recovery of the lost
renderer. Video encoding uses H.264, CRF 18, the medium preset, `yuv420p`, and
fast-start metadata at 60 fps with no audio. Zooming a native 4K still in a 4K
export enlarges captured pixels.

## Capture handoff

A PyReconstruct flow needs these inputs:

- Pointer-free PNG stills at one native canvas size, with a stable theme, window
  geometry, and fixture series. Use neutral fixture data and remove private
  names, recent-file entries, unrelated windows, and operating-system chrome.
- A targets file with the canvas width and height, top-left origin, native pixel
  units, and each target's name, frame, center `[x, y]`, and optional bounds
  `[left, top, right, bottom]`. Use these coordinates to author scene endpoints.
- A mask list with the affected frames, native pixel bounds, and an explicit
  inclusive or exclusive bounds convention. Apply opaque masks to the stills
  before rendering. Keep source hashes and mask verification with the capture.

The renderer consumes the scene and masked stills. Targets and mask lists are
capture provenance and authoring inputs, not additional renderer arguments.
It does not apply privacy masks or infer safe regions. Review every output before
using it in public docs. Internal comparison captures must stay outside the fork.

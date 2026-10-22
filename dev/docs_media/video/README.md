# Render docs videos from stills

This tool renders an animated step-through from captured images, an authored
cursor, click cues, and camera keyframes. It does not capture continuous footage
or open PyReconstruct. Pillow is already a runtime dependency. FFmpeg with
`libx264` and FFprobe must be on `PATH`, or supplied with `--ffmpeg` and `--ffprobe`.

From the repository root, render a scene:

```sh
uv run --frozen --no-default-groups python dev/docs_media/video/render.py /path/to/scene.json --output /path/to/video-1080p.mp4 --width 1920
```

The height follows the scene's aspect ratio, with black padding to the next even
pixel. Odd widths round up to the next even pixel too. Add `--height 1080` for a
1920 x 1080 frame, or use `--width 3840 --height 2160` for 4K. With an explicit
height, the camera view fits inside that frame with centered black padding.
Padding preserves the view's aspect ratio and keeps the full window visible.
The renderer refuses to overwrite an existing video.
It writes a temporary MP4 beside the destination and publishes it only after a
successful encode. A failed render removes its own temporary files.

Decode the outputs to verify frame counts and generate contact sheets:

```sh
uv run --frozen --no-default-groups python dev/docs_media/video/verify.py /path/to/video-1080p.mp4 /path/to/video-4k.mp4 --output-dir /path/to/review
```

Add `--reference-sheet /path/to/reference-sheet.jpg` to generate `comparison.jpg`.
The left panel is the reference sheet as it is. The right panel uses the first
video's decoded frames at exactly 0, 1, 2, and subsequent whole seconds.
`verification.json` records dimensions, decoded frame counts, duration, audio
stream count, byte sizes, SHA-256 hashes, and the probe and extraction commands.

Run the synthetic tests, including a short FFmpeg round trip:

```sh
uv run --frozen --no-default-groups --extra test python -m pytest dev/docs_media/video/test_render.py
```

## Scene format

Times are seconds. Coordinates use the native image canvas with the origin at
the top left, x to the right, and y down. Image paths resolve relative to the
scene file, regardless of the working directory. Every image must match `size`.

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
- A move with `to` and `controls` follows a cubic Bezier curve from the previous
  endpoint through two absolute control points. A move with `path` follows a
  polyline, as described below. The cursor holds still between moves. Moves must
  be ordered and cannot overlap.
- `clicks` lists increasing cue times. Each pulse remains anchored to the cursor's
  native position at that click. A cue does not change the image automatically.
  Author the corresponding state after the cue.
- Camera keys contain a center and a zoom of at least 1. The crop stays inside
  the source canvas. Duplicate camera values at different times create a hold.
  The last camera key holds until the end. Keep camera motion apart from clicks
  when authoring a flow.
- `cursor_size` is the arrow height at native resolution. It scales with output
  scale, independently of camera zoom. Its tip follows the transformed target.
  Optional `cursor_fade_out` starts a 0.4-second fade. When omitted, the cursor
  stays visible to the end. Optional `cursor_fade_in` hides the cursor until
  that time, then fades it in over 0.4 seconds; it must finish before the
  fade-out starts.

The renderer uses smoothstep easing for moves, camera keys, and state fades.
The cursor is a dark arrow with a white outline and a blurred shadow, and a
click shows a 0.45-second expanding blue-gray pulse. Video encoding uses
H.264, CRF 18 (`--crf` to change it), the medium preset, `yuv420p`, and
fast-start metadata at 60 fps with no audio. x264's
output depends on its thread count, so `--threads` pins it when the same frames
must give the same bytes on another machine. Zooming a native 4K still in a 4K
export enlarges captured pixels.

## Polyline moves and drags

A polyline move contains the complete path, including its starting point. This
point must equal the previous move's endpoint, or `cursor_start` for the first
move. A path needs at least two points and positive total length. Consecutive
duplicate points are allowed. A path cannot also have `to` or `controls`.

```json
{
  "start": 3.3,
  "end": 5.3,
  "path": [[812, 763], [814, 777], [813, 791], [809, 805]],
  "ease_fraction": 0.1,
  "stroke": {"color": [255, 128, 63], "width": 2, "until": 5.35}
}
```

Speed follows distance along the path. By default, the first and last 10% of
the move accelerate and brake, with constant speed between them. Vertices do
not restart the easing. `ease_fraction` sets each ramp's share of the duration,
from 0 for constant speed throughout to 0.5 for acceleration followed immediately
by braking. Existing Bezier moves retain their smoothstep timing.

An optional `stroke` draws the traveled path up to the cursor. `color` contains
three RGB integers from 0 to 255. `width` is a positive integer in native capture
pixels, so a one-point pen in a 2x capture needs width 2. The stroke scales with
the still during camera zooms and output resizing. A path without `stroke` only
moves the cursor.

The stroke stays open and unfilled during the drag, as in PyReconstruct freehand
tracing. To close a loop, end the path at its first point. The renderer draws
straight segments with Pillow; Qt rasterization and trace simplification can
differ by a few pixels. Use captured drag coordinates and check the release cut
against the finished trace.

At `end`, the cursor holds at the last point. The stroke disappears at `until`,
which defaults to `end` and cannot precede it or exceed the scene duration.
Set a cut to the finished still at `until`. Until that cut, the completed stroke
remains visible. The selection highlight or fill then comes from the still.
Do not crossfade a finished trace over its temporary stroke. Review the frames
on both sides of the cut for shifts in geometry, color, or width.

## The User Guide clips

`clips.py` authors and renders the clips in `docs/USER_GUIDE.md` from one run
of the capture script (`dev/docs_media/capture/capture.py`):

```sh
uv run --no-default-groups --extra test python dev/docs_media/capture/capture.py --out /path/to/run --guide --clips
```

That reshoots the stills, then writes each clip's scene and MP4 into
`/path/to/run/clips/` and copies the MP4s into `docs/assets/videos/user-guide/`.
To render again from an existing run without reshooting:

```sh
uv run --frozen --no-default-groups python dev/docs_media/video/clips.py /path/to/run --guide
```

Each clip is a function in `clips.py` that places its moves and clicks on the
run's `targets.json`, so a reshoot that moves a button moves the pointer with
it. The clips render at 1904 x 1292, the stills' own aspect ratio, at CRF 23
with four encoder threads. Rerunning on the same stills gives the same bytes.

## Capture inputs

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
using it in public docs.

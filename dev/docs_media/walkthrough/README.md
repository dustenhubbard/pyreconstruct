# Walkthrough videos from screenshots

`walkthrough.py` makes short how-to videos from still screen captures. It
draws a pointer, click rings, drags, key badges and camera moves on top of the
stills.
The result looks like a screen recording, but nothing is recorded live, so
there is no lag, no stray windows and nothing in the frame that was not chosen.

The User Guide's section 11 clip is made with it, from the frames
`dev/docs_media/capture/walkthrough_3d.py` shoots.

## Setup

Needs Python 3 with Pillow and NumPy (both are PyReconstruct dependencies), and
`ffmpeg` and `ffprobe` on `PATH`. From the repository root:

```sh
uv run --no-default-groups python dev/docs_media/walkthrough/walkthrough.py --help
```

## Screencast size

A screencast shows PyReconstruct the way a 1280 x 720 screen shows it, at 2x.
Shoot the window at 1280 x 720 logical pixels on a 2x screen, so each still is
2560 x 1440, keep the camera at zoom 1, and render at `--width 2560`. Then no
frame is scaled up or down. `--crf 21` keeps the file small with no visible
loss. Keep fine grain out of demo images: noise is what makes a video file
large.

## Workflow

1. **Plan the steps.** Write down each screen and the one control clicked to
   reach the next. One video shows one task. Keep the written steps on the page
   beside the video.
2. **Capture the stills.** One PNG per screen state, all the same size, with no
   pointer in them. Use a made-up series, never real data, and show no home
   paths, user names or recent-file lists.
3. **Write `steps.json`.** Measure each click target on the still itself
   (center, in native pixels):

   ```json
   {
     "size": [2560, 1440],
     "images": {"open": "01-open.png", "menu": "02-menu.png", "done": "03-done.png"},
     "targets": {"lists_menu": [410, 18], "object_list_row": [622, 62]},
     "camera_start": {"x": 1280, "y": 720, "zoom": 1},
     "camera_end": {"x": 1280, "y": 720, "zoom": 1},
     "steps": [
       {"image": "open", "click": "lists_menu", "camera": {"x": 1280, "y": 720, "zoom": 1}},
       {"image": "menu", "click": "object_list_row", "after": "done",
        "camera": {"x": 1280, "y": 720, "zoom": 1}}
     ]
   }
   ```

   Each step names the screen showing and the target to `click` (or `point`
   at, or `drag` along). The next step's screen appears just after the click
   or the release. Step options:

   | Key | Meaning |
   | --- | --- |
   | `click` / `point` | Target name or `[x, y]`. `point` moves the pointer without a click |
   | `drag` | Target name with `"points"`, or a list of `[x, y]`: press at the first point, move along the path at an even speed, release at the last |
   | `drag_time` | Seconds from press to release (default 2.0) |
   | `stroke` | `{"color": [r, g, b], "width": 2}`: the drag draws a line behind the pointer, in native pixels, until the next screen has fully shown |
   | `frames` | Screens shown in turn during the drag, each as the pointer covers its share of the path (a 3D turn, for example) |
   | `fade` | `true` or seconds: cross-fade into this step's screen (menus, dialogs). Plain changes cut |
   | `after`, `after_fade` | Screen shown after the last step's click |
   | `dwell` | Extra seconds to rest on the target before the click |
   | `move` | Seconds for this pointer move (default 1.6) |
   | `zoom`, `camera` | Zoom, or a fixed `{"x", "y", "zoom"}` view, for this step |
   | `keys` | A key badge at the bottom center, such as `"⇧ Shift"`, from just before the pointer arrives to just after the click |
   | `end_dwell` | Seconds to hold after the last step |
   | `type` | `{"box": [x0, y0, x1, y1], "duration": 2.4}`: type in this step's text, captured already typed |

   Top-level `timing` overrides the defaults in `DRAFT` in `walkthrough.py`.
   Top-level `loop`, `true` or seconds, is for a clip that plays on a loop:
   the pointer fades in at the start, the camera returns to its opening view
   (in place of `camera_end`), and once everything else has finished (pointer,
   fades, badges, rings, camera) the first screen fades back in (0.4 s by
   default), so the loop has no jump.
4. **Draft, preview and render:**

   ```sh
   W="uv run --no-default-groups python dev/docs_media/walkthrough/walkthrough.py"
   $W draft frames/steps.json
   $W sheet frames/scene.json -o sheet.jpg
   $W render frames/scene.json --width 2560 --crf 21 -o clip.mp4
   $W verify frames/scene.json clip.mp4
   ```

   `draft` writes `scene.json` beside the steps. The sheet shows one frame per
   second: check that every click lands on its control. `render` writes H.264,
   60 fps, `yuv420p`, no audio, fast start. `verify` writes
   `verification.json` beside the scene (size, frame count, hashes).

## Scene format

`scene.json` holds everything the renderer needs. Coordinates are native
pixels of the stills.

| Key | Meaning |
| --- | --- |
| `size` | `[width, height]` of every still |
| `duration`, `fps` | Seconds (frames = duration x fps); fps defaults to 60 |
| `images` | Name to path, relative to the scene file |
| `states` | `[{time, image, fade?}]`: which still shows from `time` on |
| `cursor_start` | Pointer position at time 0 |
| `moves` | `[{start, end, to, controls?}]`: cubic Bézier pointer moves, or `[{start, end, path, ease?, stroke?}]`: drags along a polyline |
| `clicks` | Times of click rings, at the pointer position |
| `cursor_fade_in`, `cursor_fade_out` | Times the pointer fades in or out |
| `camera` | `[{time, x, y, zoom}]`: view center and zoom, kept inside the still |
| `keys` | `[{start, end, text}]`: key badges, faded in and out |
| `targets` | Optional names for points |
| `cursor_size`, `style` | Optional overrides of `STYLE` in `walkthrough.py` |

Motion uses smootherstep easing for the camera, the pointer and cross-fades.
A drag keeps an even speed between a short speed-up and slow-down, each `ease`
of its time (default 0.1). Its `stroke`, `{color, width, until?}`, grows
behind the pointer and stays whole until `until` (default the drag's end).
The key badges use the macOS system font; elsewhere Pillow's own font stands
in, which has no key symbols.

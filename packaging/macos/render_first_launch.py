"""Render the first-launch guide for the app in one disk image.

    python3 packaging/macos/render_first_launch.py "<app name>" <dev|stable> <icon.png> <out.html>

The icon and the macOS screenshots are embedded as data URIs, so the guide is
one file that works offline.
"""

import base64
import struct
import sys
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "first-launch.html"
SHOTS = HERE / "first-launch"


def data_uri(png):
    return "data:image/png;base64," + base64.b64encode(Path(png).read_bytes()).decode("ascii")


def half_width(png):
    """Show a Retina screenshot at its true size: half its pixel width."""
    return struct.unpack(">I", Path(png).read_bytes()[16:20])[0] // 2


def render(app_name, flavor, icon_png):
    page = TEMPLATE.read_text(encoding="utf-8").replace("@APP_NAME@", app_name)
    page = page.replace("@ICON_DATA@", data_uri(icon_png))
    for n in (1, 2, 3, 4):
        shot = SHOTS / f"{flavor}-{n}.png"
        page = page.replace(f'src="@SHOT_{n}@"',
                            f'width="{half_width(shot)}" src="{data_uri(shot)}"')
    return page


if __name__ == "__main__":
    app_name, flavor, icon_png, out = sys.argv[1:5]
    Path(out).write_text(render(app_name, flavor, icon_png), encoding="utf-8")

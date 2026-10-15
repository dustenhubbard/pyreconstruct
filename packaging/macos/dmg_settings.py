# dmgbuild settings for the drag-to-Applications window. dmgbuild writes the
# Finder view (.DS_Store) itself and never runs Finder or AppleScript, so it
# works on headless CI runners. make_dmg.sh passes:
#   -D app=<path to the .app>  -D background=<path to dmg-background.png>
#   -D guide=<path to Read Before First Launch.html>   (unsigned apps only)
# The positions must match the chevron drawn by make_dmg_background.py.
# window_rect is the whole window, title bar included. The heights leave room
# for Finder's path and status bars, which follow the user's Finder settings.
import os.path

defines = globals()["defines"]   # dmgbuild runs this file with its -D values here
app = defines["app"]
app_name = os.path.basename(app)
guide = defines.get("guide", "")

format = "UDZO"
filesystem = "HFS+"

files = [app]
symlinks = {"Applications": "/Applications"}
hide_extensions = [app_name]

background = defines["background"]
icon_size = 160
text_size = 12
show_toolbar = False
show_sidebar = False
show_status_bar = False
show_pathbar = False
show_tab_view = False
default_view = "icon-view"

icon_locations = {
    app_name: (180, 170),
    "Applications": (480, 170),
}

# The guide sits under the chevron, in a taller window, so the two icons and
# the arrow between them stay where a signed image puts them.
if guide:
    files.append(guide)
    icon_locations[os.path.basename(guide)] = (330, 380)
    window_rect = ((200, 120), (660, 622))
else:
    window_rect = ((200, 120), (660, 422))

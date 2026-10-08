import os
from pathlib import Path

def createHiddenDir(jser_dir, series_name):
    """Create a hidden folder to contain the individual section and series files.

    A folder already there loses the files directly in it. A folder inside
    it (a backup folder set there, which a close keeps) stays with all it
    holds, and so does the folder itself.
    """
    hidden_dir = os.path.join(jser_dir, f".{series_name}")
    # check if the folder exists, clear its files if it does
    if os.path.isdir(hidden_dir):
        for f in os.listdir(hidden_dir):
            fp = os.path.join(hidden_dir, f)
            if not os.path.isdir(fp) or os.path.islink(fp):
                os.remove(fp)
    else:
        # create the folder
        os.mkdir(hidden_dir)
    if os.name == "nt":  # manually hide if windows
        import subprocess
        subprocess.check_call(["attrib", "+H", hidden_dir])
    
    return hidden_dir

def createNewSeriesDir(parent_dir, series_name):
    """Create an empty hidden folder for a series that is being made.

    Unlike createHiddenDir, this never empties or removes a folder that is
    already there. `.<name>` can belong to a series open in another window,
    hold unsaved work from a session that did not close, or, in the home
    folder fallback, be any dot folder at all (`.ssh` for a series named
    "ssh"). So the first of `.<name>`, `.<name>-2`, `.<name>-3`, ... that is
    free is used.

    A name is also skipped when `<name>.jser` is in the folder, because
    `.<name>` is where opening that file looks for its working folder, its
    unsaved work, and its in-use heartbeat. Taking it would make that file
    look locked, offer this series as its unsaved work, and let importing
    from it empty this series' folder.

    The folder name is not the series name (that comes from the .ser file),
    and Save As moves the folder to `.<jser name>`.

        Params:
            parent_dir (str): the folder to create the hidden folder in
            series_name (str): the name of the new series
        Returns:
            (str): the path of the new, empty folder
    """
    n = 1
    while True:
        stem = series_name if n == 1 else f"{series_name}-{n}"
        n += 1
        if os.path.exists(os.path.join(parent_dir, f"{stem}.jser")):
            continue
        hidden_dir = os.path.join(parent_dir, f".{stem}")
        try:
            os.mkdir(hidden_dir)
            break
        except FileExistsError:
            continue
    if os.name == "nt":  # manually hide if windows
        import subprocess
        subprocess.check_call(["attrib", "+H", hidden_dir])

    return hidden_dir

from .frozen import is_frozen, bundle_base

if is_frozen():  # assets bundled at <_MEIPASS>/PyReconstruct/assets
    src_dir = bundle_base() / "PyReconstruct"
else:
    src_dir = Path(os.path.realpath(__file__)).parents[2]

assets_dir          =  os.path.join(src_dir, "assets")
welcome_series_dir  =  os.path.join(assets_dir, "welcome_series", ".welcome")
img_dir             =  os.path.join(assets_dir, "img")
icon_path           =  os.path.join(img_dir, "PyReconstruct.ico")

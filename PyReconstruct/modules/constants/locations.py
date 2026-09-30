import os
from pathlib import Path

def createHiddenDir(jser_dir, series_name):
    """Create a hidden folder to contain the individual section and series files."""    
    hidden_dir = os.path.join(jser_dir, f".{series_name}")
    # check if the folder exists, delete if it does
    if os.path.isdir(hidden_dir):
        for f in os.listdir(hidden_dir):
            os.remove(os.path.join(hidden_dir, f))
        os.rmdir(hidden_dir)
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
    "ssh"). When `.<name>` is taken, the next free `.<name>-2`, `.<name>-3`,
    ... is used instead. The folder name is not the series name (that comes
    from the .ser file), and Save As moves the folder to `.<jser name>`.

        Params:
            parent_dir (str): the folder to create the hidden folder in
            series_name (str): the name of the new series
        Returns:
            (str): the path of the new, empty folder
    """
    hidden_dir = os.path.join(parent_dir, f".{series_name}")
    n = 1
    while True:
        try:
            os.mkdir(hidden_dir)
            break
        except FileExistsError:
            n += 1
            hidden_dir = os.path.join(parent_dir, f".{series_name}-{n}")
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

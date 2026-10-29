import threading


def _import_trimesh_on_own_thread():
    """Import trimesh with nothing of ours on the stack.

    trimesh keeps the ImportError of every optional extra it lacks (pyembree,
    rtree, svg.path, mapbox_earcut, ...) and raises it when that feature is
    used. Each error's traceback holds the import frames, and each frame holds
    its caller through f_back, so the whole stack that first imported trimesh
    stays alive for the rest of the process. That stack is usually
    MainWindow.openSeries building the menus, so the series it opened was
    never freed after the next open.

    A fresh thread's stack ends at the thread itself. A failed import is left
    for the module imports below to raise in the caller, as before.
    """
    def run():
        try:
            import trimesh  # noqa: F401
        except Exception:
            pass

    thread = threading.Thread(target=run, name="import-trimesh")
    thread.start()
    thread.join()


_import_trimesh_on_own_thread()

from .generate_volumes import generateVolumes
from .export_volumes import *
from .objects_3D import Surface, Spheres

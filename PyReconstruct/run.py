import os, sys, importlib
from pathlib import Path

# In a frozen build, multiprocessing (spawn -- the default on macOS and Windows)
# re-runs THIS executable for every worker process. Intercept that re-launch
# here, before the heavy GUI/VTK imports below, so a worker runs its task
# instead of importing the GUI and opening a window. Otherwise each worker
# launches its own main window (fork-bombing the Dock with one window per
# worker) and the actual job stalls because no real workers ever start. This is
# a no-op for the normal launch and for the "__run_script__" dispatch.
if getattr(sys, "frozen", False):
    import multiprocessing
    multiprocessing.freeze_support()

import PySide6
from PySide6.QtWidgets import QApplication


if __name__ == "__main__":

    # set up imports for run.py location
    run_script = Path(__file__)
    pypath = str(run_script.parents[1])
    sys.path.append(pypath)


import PyReconstruct.modules.gui.main as main


def runPyReconstruct(filename=None):

    # Stopgap for Wayland Qt issue (only needed from source; in a frozen bundle
    # PyInstaller's PySide6 hook wires the plugin path, and this PySide6.__file__
    # location would be wrong).
    # stackoverflow.com/questions/68417682/qt-and-opencv-app-not-working-in-virtual-environment
    if not getattr(sys, "frozen", False):
        ps6_dir = Path(PySide6.__file__).parent
        qt_plugins = ps6_dir / "Qt/plugins"
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_plugins)

    # create the Qt Application
    app = QApplication(sys.argv)

    # run program until the user closes without requesting a restart (all
    # platforms quit on closing the window; the in-app Restart reloads modules
    # and recreates the window)
    run = True
    while run:

        main_window = main.MainWindow(filename)
        app.exec()

        if main_window.restart_mainwindow:  # restart requested

            if not main_window.series.isWelcomeSeries():
                filename = main_window.series.jser_fp

            # reload PyReconstruct modules
            loaded_modules = list(sys.modules.items())
            for module_name, module in loaded_modules:
                if module_name.startswith("PyReconstruct.modules"):
                    importlib.reload(module)

        else:  # no restart requested

            run = False


if __name__ == "__main__":

    # Frozen-build script dispatcher: a PyInstaller exe can't execute an
    # arbitrary .py via sys.executable, so bundled helper scripts are relaunched
    # as `<exe> __run_script__ <script.py> [args...]` and run here via runpy.
    if len(sys.argv) > 2 and sys.argv[1] == "__run_script__":

        import runpy
        script = sys.argv[2]
        sys.argv = [script] + sys.argv[3:]
        runpy.run_path(script, run_name="__main__")

    elif "--selftest" in sys.argv[1:]:

        # The GUI import chain above no longer pulls the heavy 3D / scientific
        # deps (vtk, vedo, trimesh, scipy, skimage) -- they're imported lazily
        # when their features run, which is what keeps launch fast. Import them
        # explicitly here so this frozen self-test still catches missing-module
        # bundling regressions (e.g. a hiddenimport dropped from the spec) that
        # would otherwise only surface when the user opens the 3D viewer.
        import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  (GL2 render factory)
        import vtk  # noqa: F401
        import PyReconstruct.modules.gui.popup.custom_plotter  # noqa: F401  (vedo + vtk.qt)
        from PyReconstruct.modules.backend.volume import export3DObjects  # noqa: F401  (trimesh)
        import scipy.interpolate  # noqa: F401
        import skimage.draw  # noqa: F401
        # Reaching here means the full GUI + 3D/scientific import chain succeeded.
        # CI runs the frozen exe with this flag to catch windowed-only import
        # failures (e.g. None stdout) without launching the UI.
        print("selftest ok")
        sys.exit(0)

    else:

        filename = sys.argv[1] if len(sys.argv) > 1 else None
        runPyReconstruct(filename)

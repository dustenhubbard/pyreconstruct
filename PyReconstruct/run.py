import os, sys, importlib
from pathlib import Path

# In-place update helper: `<exe> __apply_update__ <staging> [--pid N]` swaps a
# staged build into place after this app quits. It has to run before anything
# below imports Qt, since the swap renames the folder Qt would load from, and
# it only ever runs on that exact first argument. apply.py is stdlib only; the
# package imports on the way to it (the updater and constants packages) pull
# in no Qt either, which tests/test_run_apply_dispatch.py checks.
if len(sys.argv) > 1 and sys.argv[1] == "__apply_update__":
    if not getattr(sys, "frozen", False):
        sys.path.append(str(Path(__file__).parents[1]))
    from PyReconstruct.modules.backend.updater.apply import main as _apply_update
    sys.exit(_apply_update(sys.argv[2:]))

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
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication


class FileOpenWatcher(QObject):
    """Route macOS open-document events (a double-clicked .jser) into the app.

    macOS hands a double-clicked file to the app as a QFileOpenEvent, never as
    argv, both at launch and while running. Before the main window exists the
    path parks in ``pending`` (runPyReconstruct spins the event loop once to
    collect it); after that the event opens the series in the live window.
    Windows and Linux pass the path as argv and never send this event, so the
    filter is a no-op there.
    """

    def __init__(self):
        super().__init__()
        self.pending = None
        self.main_window = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if path:
                if self.main_window is not None:
                    self.main_window.openSeries(jser_fp=path)
                else:
                    self.pending = path
            return True
        return super().eventFilter(obj, event)


if __name__ == "__main__":

    # set up imports for run.py location
    run_script = Path(__file__)
    pypath = str(run_script.parents[1])
    sys.path.append(pypath)


import PyReconstruct.modules.gui.main as main


def runPyReconstruct(filename=None):

    # Tee stdout/stderr to a per-user log file so the packaged (windowed) app,
    # which has no console, still records tracebacks and diagnostic output the
    # CLI launcher used to show. Done here (not at module import) so the frozen
    # multiprocessing worker re-execs -- which exit via freeze_support() before
    # reaching this -- never install it and can't clash over the log file.
    try:
        from PyReconstruct.modules.backend.func.logging_setup import install_file_logging
        install_file_logging()
    except Exception:
        pass  # logging is best-effort; never block launch on it

    # Stopgap for Wayland Qt issue (only needed from source; in a frozen bundle
    # PyInstaller's PySide6 hook wires the plugin path, and this PySide6.__file__
    # location would be wrong).
    # stackoverflow.com/questions/68417682/qt-and-opencv-app-not-working-in-virtual-environment
    if not getattr(sys, "frozen", False):
        ps6_dir = Path(PySide6.__file__).parent
        qt_plugins = ps6_dir / "Qt/plugins"
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_plugins)

    # the first launch after settings moved from the KHLab organization to
    # PyReconstruct copies the old stores across (once, leaving them in
    # place); then a flavored build's first launch on the shared settings
    # store folds its old private domain in (once; the stable app is a no-op).
    # The fold waits while a copy still needs a retry: folding first could
    # put a Dev value where the stable one belongs, or mark an empty Dev
    # store as folded, and the retry could not undo either.
    from PyReconstruct.modules.constants.settings_domain import (
        copy_legacy_settings_once,
        fold_flavor_settings_once,
    )
    if copy_legacy_settings_once().complete:
        fold_flavor_settings_once()

    # create the Qt Application
    app = QApplication(sys.argv)

    # catch a double-clicked .jser (macOS sends it as an event once the loop
    # spins; one processEvents pass collects a launch-time double-click so the
    # first window opens straight into that series instead of the welcome one)
    file_open_watcher = FileOpenWatcher()
    app.installEventFilter(file_open_watcher)
    app.processEvents()
    if filename is None and file_open_watcher.pending is not None:
        filename = file_open_watcher.pending
        file_open_watcher.pending = None

    # push menu shortcut keybinds clear of their labels (the native style packs
    # them within a few pixels of the widest label). A QProxyStyle survives the
    # setTheme stylesheet swaps, so it is installed once, here.
    from PyReconstruct.modules.gui.utils import MenuShortcutSpacingStyle
    app.setStyle(MenuShortcutSpacingStyle())

    # run program until the user closes without requesting a restart (all
    # platforms quit on closing the window; the in-app Restart reloads modules
    # and recreates the window)
    run = True
    while run:

        main_window = main.MainWindow(filename)
        file_open_watcher.main_window = main_window
        app.exec()
        file_open_watcher.main_window = None

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
        # PNG section export draws its SVG with QtSvg. Render a tiny one here,
        # so a build that dropped QtSvg fails now rather than on a user's
        # first export (no installer could export PNG before this moved off
        # cairosvg).
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
        _svg = QSvgRenderer(QByteArray(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
            b'<rect width="4" height="4" fill="#ff0000"/></svg>'
        ))
        _img = QImage(4, 4, QImage.Format_ARGB32)
        _img.fill(Qt.transparent)
        _p = QPainter(_img)
        _svg.render(_p)
        _p.end()
        if _img.pixelColor(2, 2).red() != 255:
            print("selftest failed: QtSvg did not render")
            sys.exit(1)
        # The updater checks release signatures with its own Ed25519 code and
        # hashlib's BLAKE2b; make sure both work in this build.
        from PyReconstruct.modules.backend.updater import minisign as _minisign
        from PyReconstruct.modules.backend.updater.signing_keys import TRUSTED_KEYS
        if not _minisign.selftest(TRUSTED_KEYS):
            print("selftest failed: update signature check does not work")
            sys.exit(1)
        # Reaching here means the full GUI + 3D/scientific import chain succeeded.
        # CI runs the frozen exe with this flag to catch windowed-only import
        # failures (e.g. None stdout) without launching the UI.
        print("selftest ok")
        sys.exit(0)

    else:

        filename = sys.argv[1] if len(sys.argv) > 1 else None
        runPyReconstruct(filename)

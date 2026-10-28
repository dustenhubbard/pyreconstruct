"""Child process for tests/test_perf_gates.py: measure one step on a large series.

Run as ``python perf_gate_child.py <step> <jser> <out.json>``. Each run is a
fresh process, so the peak memory it reports belongs to this one step alone.

Steps:

- ``convert``: open a legacy .jser headless and save it in the current layout to
  ``<out.json>``'s path with a .jser suffix (benchmarks/make_scaled_series.py
  reads only the current layout).
- ``open``: wall time of ``MainWindow(jser)`` plus one event drain, the open a
  user waits for.
- ``memory``: the same open, reporting the process peak resident size
  (``VmHWM`` on Linux, ``ru_maxrss`` elsewhere).
- ``section``: after the open, the median wall time of a section change
  (``MainWindow.changeSection``, two event drains and a field grab) over
  neighbor sections and far jumps, in a 1920x1080 window.
- ``save``: after the open, the wall time of a save with no edits
  (``MainWindow.saveToJser``), and whether the .jser was rewritten.

The application settings are redirected before anything reads them: an
in-memory settings store, and tests/qsettings_isolation.py for every QSettings
the window builds. The caller also points XDG_CONFIG_HOME at a scratch folder.
"""

import json
import os
import resource
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYRECON_UNATTENDED"] = "1"

import qsettings_isolation  # noqa: E402,F401  (redirects QSettings on import)

from PyReconstruct.modules.backend.settings_store import (  # noqa: E402
    DictSettingsStore,
    set_default_settings_store,
)

set_default_settings_store(DictSettingsStore())

# sections visited by the section step: neighbors of the opening section, then
# jumps across the series, repeated so one slow draw does not set the median
SECTION_STEPS = (1, 2, 3, "far", 1, 2, 3, "far", 1, 2, 3, "far")


def peak_rss_mb():
    """Peak resident size of this process so far, in MB."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # bytes on macOS, KB on Linux
    return peak / (1 << 20) if sys.platform == "darwin" else peak / 1024


def convert(src, out):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series

    dst = os.path.splitext(out)[0] + ".jser"
    series = Series.openJser(src, progress=NullProgressReporter)
    series.saveJser(save_fp=dst)
    result = {"jser": dst, "sections": len(series.sections)}
    series.close()
    return result


def drain(app, rounds=5):
    for _ in range(rounds):
        app.processEvents()


def open_window(jser):
    """Build the window the way PyReconstruct opens a .jser. Returns the
    window, the application and the wall time in seconds."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["perf-gate"])
    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP,
        ORG,
        current_version_str,
    )
    from PyReconstruct.modules.gui.main import main_window as mw_mod
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    # QSettings is the isolated class here (see the module docstring)
    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    QSettings(ORG, APP).setValue("update_check_on_startup", False)
    # no prompt can be answered offscreen; the steps below should raise none
    mw_mod.saveNotify = lambda *a, **k: "no"
    mw_mod.unsavedNotify = lambda *a, **k: False

    t0 = time.perf_counter()
    mw = mw_mod.MainWindow(jser)
    drain(app)
    wall = time.perf_counter() - t0
    for timer in ("update_check_timer", "whats_new_timer"):
        if getattr(mw, timer, None) is not None:
            getattr(mw, timer).stop()
    return mw, app, wall


def traces_in_view(mw):
    return len(getattr(mw.field.section_layer, "traces_in_view", []) or [])


def section_changes(mw, app):
    series = mw.series
    mw.resize(1920, 1080)
    drain(app)
    mw.field.grab()
    snums = sorted(series.sections)
    i = snums.index(series.current_section) if series.current_section in snums else 0
    walls, drawn = [], []
    for k, step in enumerate(SECTION_STEPS):
        if step == "far":
            i = (i + len(snums) // 3 + k) % len(snums)
        else:
            i = (i + step) % len(snums)
        t0 = time.perf_counter()
        mw.changeSection(snums[i])
        drain(app, 2)
        mw.field.grab()
        walls.append(time.perf_counter() - t0)
        drawn.append(traces_in_view(mw))
    return statistics.median(walls), {"walls_s": walls, "traces_in_view": drawn}


def save(mw):
    jser = mw.series.jser_fp
    before = os.stat(jser).st_mtime_ns
    t0 = time.perf_counter()
    result = mw.saveToJser(notify=False)
    wall = time.perf_counter() - t0
    return wall, {"jser_written": os.stat(jser).st_mtime_ns != before,
                  "result": result}


def main():
    step, jser, out = sys.argv[1:4]
    report = {"step": step, "jser": jser, "pid": os.getpid(),
              "load_start": list(os.getloadavg())}
    if step == "convert":
        report.update(convert(jser, out))
    else:
        mw, app, open_s = open_window(jser)
        report["open_s"] = open_s
        report["sections"] = len(mw.series.sections)
        if step == "open":
            report["value"] = open_s
        elif step == "memory":
            report["value"] = peak_rss_mb()
        elif step == "section":
            report["value"], report["detail"] = section_changes(mw, app)
        elif step == "save":
            report["value"], report["detail"] = save(mw)
        else:
            raise SystemExit(f"unknown step {step!r}")
        report["peak_rss_mb"] = peak_rss_mb()
        mw.series.modified = False
        mw.close()
        drain(app)
    report["load_end"] = list(os.getloadavg())
    with open(out, "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()

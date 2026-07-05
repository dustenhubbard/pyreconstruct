#!/usr/bin/env python
"""Object List build benchmark: eager QTableWidget vs lazy model/view.

Measures, for a synthetic series of N objects, the cost of standing up the
Object List the OLD way (a QTableWidget with one QTableWidgetItem per cell,
built for every object up front, plus resizeRowsToContents) versus the NEW way
(an ObjectTableModel that only builds the rows in the visible window).

Emits JSON. Run in a fresh interpreter so peak RSS reflects one path at a time:

  QT_QPA_PLATFORM=offscreen PYTHONPATH=<checkout> python benchmarks/bench_object_list.py old  100000
  QT_QPA_PLATFORM=offscreen PYTHONPATH=<checkout> python benchmarks/bench_object_list.py new  100000

The synthetic getItems is deliberately trivial so the numbers isolate the
table-construction cost (item materialization + layout), not geometry.
"""
import os, sys, json, time, resource

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

COLUMNS = [("Range", True), ("Host", True), ("Groups", True),
           ("Locked", True), ("Last user", True), ("Comment", True)]
STATIC = ["Name"]
VISIBLE_ROWS = 50  # a tall Object List shows ~30-50 rows at once


def headers():
    h = ["Name"]
    for k, b in COLUMNS:
        if not b:
            continue
        if k == "Range":
            h += ["Start", "End"]
        else:
            h.append(k)
    return h


def make_items(QTableWidgetItem, name, key):
    if key == "Name":
        return [QTableWidgetItem(name)]
    if key == "Range":
        return [QTableWidgetItem("0"), QTableWidgetItem("9")]
    if key == "Locked":
        from PySide6.QtCore import Qt
        it = QTableWidgetItem("")
        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        it.setCheckState(Qt.CheckState.Unchecked)
        return [it]
    return [QTableWidgetItem(f"{name}:{key}")]


def run_old(names, QTableWidgetItem):
    from PySide6.QtWidgets import QTableWidget
    h = headers()
    t0 = time.perf_counter()
    tw = QTableWidget(len(names), len(h))
    built = 0
    for r, name in enumerate(names):
        col = 0
        for key in STATIC:
            for it in make_items(QTableWidgetItem, name, key):
                tw.setItem(r, col, it); col += 1; built += 1
        for key, b in COLUMNS:
            if b:
                for it in make_items(QTableWidgetItem, name, key):
                    tw.setItem(r, col, it); col += 1; built += 1
    tw.resizeRowsToContents()
    dt = time.perf_counter() - t0
    return dt, built


def run_new(names, QTableWidgetItem):
    from PyReconstruct.modules.gui.table.object_model import ObjectTableModel
    from PyReconstruct.modules.gui.utils import sortList
    from PySide6.QtCore import Qt

    class Src:
        static_columns = STATIC
        columns = COLUMNS
        def __init__(self, names): self._names = names; self.built = 0
        def getHeaders(self): return headers()
        def getFiltered(self): return sortList(self._names)
        def getItems(self, name, key):
            self.built += 1
            return make_items(QTableWidgetItem, name, key)

    t0 = time.perf_counter()
    src = Src(names)
    model = ObjectTableModel(src)
    n_cols = model.columnCount()
    # render only the visible window, as the view would
    for r in range(min(VISIBLE_ROWS, model.rowCount())):
        for c in range(n_cols):
            model.data(model.index(r, c), Qt.DisplayRole)
            model.flags(model.index(r, c))
    dt = time.perf_counter() - t0
    return dt, src.built


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "new"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000

    from PySide6.QtWidgets import QApplication, QTableWidgetItem
    QApplication.instance() or QApplication(["bench"])

    names = [f"obj_{i:06d}" for i in range(n)]
    if mode == "old":
        dt, built = run_old(names, QTableWidgetItem)
    else:
        dt, built = run_new(names, QTableWidgetItem)

    res = {
        "mode": mode, "n_objects": n, "wall_s": round(dt, 4),
        "items_built": built,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }
    print(json.dumps(res))


if __name__ == "__main__":
    main()

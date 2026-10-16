"""Run by ``test_settings_copy_restart.py`` in a pytest process of its own.

The in-app Restart (``run.runPyReconstruct``) reloads every
``PyReconstruct.modules`` module inside the same process, and Qt keeps its
parse of a settings file across that reload. A damaged old file that failed to
parse must stay owed after it: the next ``QSettings`` on the file is handed the
first, partial parse with no error, and copying that would mark the store done
for good. These tests reload modules, which would change the classes every
later test in a shared session sees, so they run on their own.
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import qsettings_isolation
from PyReconstruct.modules.constants import settings_domain as D

from settings_copy_helpers import DAMAGED

pytestmark = pytest.mark.gui


def _damage(app):
    path = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    assert str(path).startswith(qsettings_isolation.isolation_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DAMAGED)
    return path


def _window_store(main_window):
    app = D.SHARED_APP + "-" + main_window.series.code
    new = QSettings(D.SETTINGS_ORG, app)
    new.remove(D.LEGACY_COPY_MARKER)
    new.sync()
    D._copy_pending.pop(app, None)
    return app, new


def test_module_reload_keeps_corrupt_source_owed(qapp):
    code = "RELOAD_CORRUPT_COPYTEST"
    app = D.SHARED_APP + "-" + code
    path = _damage(app)
    assert D.copy_legacy_series_settings_once(code).complete is False
    assert app in D._unparsable_legacy
    importlib.reload(D)
    assert path.read_text() == DAMAGED
    result = D.copy_legacy_series_settings_once(code)
    assert result.complete is False
    assert not QSettings(D.SETTINGS_ORG, app).contains(D.LEGACY_COPY_MARKER)


def test_real_window_series_reopen_after_restart_keeps_corrupt_source_owed(
    main_window,
):
    app, new = _window_store(main_window)
    _damage(app)
    main_window._foldSeriesSettings()
    assert app in D._unparsable_legacy
    assert not new.contains(D.LEGACY_COPY_MARKER)
    importlib.reload(D)
    main_window._foldSeriesSettings()
    assert not new.contains(D.LEGACY_COPY_MARKER)
    assert D.legacy_copy_pending(app)


def test_actual_restart_reload_loop_keeps_corrupt_series_owed(main_window):
    from PyReconstruct import run

    app, new = _window_store(main_window)
    path = _damage(app)
    main_window._foldSeriesSettings()
    assert app in D._unparsable_legacy
    assert not new.contains(D.LEGACY_COPY_MARKER)
    # run the reload statements of the in-app Restart as they stand in
    # run.runPyReconstruct; running the function itself would start a second
    # QApplication and event loop
    function = ast.parse(inspect.getsource(run.runPyReconstruct)).body[0]
    loop = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Tuple)
        and [e.id for e in node.target.elts] == ["module_name", "module"]
    )
    listing = ast.parse("loaded_modules = list(sys.modules.items())").body[0]
    block = ast.fix_missing_locations(
        ast.Module(body=[listing, loop], type_ignores=[])
    )
    exec(compile(block, "<in-app Restart reload block>", "exec"), run.__dict__, {})
    qsettings_isolation.verify_isolated()
    assert path.read_text() == DAMAGED
    assert app in D._unparsable_legacy
    main_window._foldSeriesSettings()
    assert not new.contains(D.LEGACY_COPY_MARKER)
    assert not new.contains("broken/entry")

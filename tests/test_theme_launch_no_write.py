"""A launch draws the stored theme and writes nothing to the theme setting.

Starting PyReconstruct used to store the ``theme`` key on every launch: a
missing key got its default written back by ``Series.getOption``, and
``setTheme`` stored the value it had just been handed. A user who never
picked a theme had one saved for them, and a launch alone changed the
settings file. The launch now draws through ``MainWindow.applyTheme``, which
stores nothing, and reads the key with ``write_default=False``. Picking a
theme (Change theme..., Series ▸ Options) still stores the choice.

The launch tests build a real ``MainWindow`` on an in-memory default store,
so the whole constructor runs against a store the test can inspect. They run
as the build they are on, and once more as the macOS Dev app with its native
controls (``appearance.native()`` stubbed on, since ``sys.platform`` cannot be
patched under a constructor that imports scipy). The ``window`` tests drive
``applyTheme`` and ``setTheme`` on the shared fixture window across the
builds that draw a theme differently (``appearance.py``), patched the way
``test_mac_appearance.py`` patches them.
"""
import sys

import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    default_settings_store,
    set_default_settings_store,
)
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.gui.utils import appearance

pytestmark = pytest.mark.gui

MAC_DEV = ("darwin", True)
STABLE = ("linux", False)


@pytest.fixture
def restore_look(qapp):
    """Leave the app's sheet, palette and scheme as the test found them."""
    hints = QApplication.styleHints()
    sheet, scheme = qapp.styleSheet(), hints.colorScheme()
    yield
    qapp.setStyleSheet(sheet)
    qapp.setProperty(appearance.QDARKSTYLE_PROPERTY, False)
    hints.unsetColorScheme()
    qapp.setPalette(qapp.style().standardPalette())
    assert hints.colorScheme() == scheme


@pytest.fixture
def build(monkeypatch, restore_look):
    """Call with (platform, dev) to run as that build; appearance.native()
    decides from these."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setenv("PYRECON_MAC_UI", "1")

    def pick(platform, dev):
        monkeypatch.setattr(sys, "platform", platform)
        version = "1.25.0.dev5+g0123abc" if dev else "1.24.0"
        monkeypatch.setattr(build_flavor, "running_version", lambda: version)
    return pick


@pytest.fixture
def memory_store():
    """The process default store swapped for an empty in-memory one, so a
    MainWindow built here reads and writes settings the test can see."""
    original = default_settings_store()
    store = DictSettingsStore()
    set_default_settings_store(store)
    yield store
    set_default_settings_store(original)


@pytest.fixture
def launch(qapp, series_jser, qsettings_snapshot, main_window_dialogs):
    """Build a MainWindow on the fixture series the way the main_window
    fixture does, and close it before the default store is restored."""
    import sys as _sys

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP, ORG, current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    windows = []
    previous_excepthook = _sys.excepthook

    def start():
        QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
        window = MainWindow(str(series_jser))
        window._captureListLayout = lambda: None
        windows.append(window)
        return window

    yield start

    _sys.excepthook = previous_excepthook
    for window in windows:
        window.series.modified = False
        window.close()
        window.deleteLater()


@pytest.fixture(params=[False, True], ids=["this build", "mac dev"])
def native(request, monkeypatch, restore_look):
    """Run as the build this test is on, or as the macOS Dev app with
    PYRECON_MAC_UI=1, where every theme keeps the native controls."""
    if request.param:
        monkeypatch.setattr(appearance, "mac_ui_enabled", lambda: True)
    return request.param


def test_launch_leaves_an_absent_theme_absent(memory_store, native, launch):
    assert not memory_store.contains(None, "theme")
    launch()
    assert not memory_store.contains(None, "theme")


def test_launch_draws_a_stored_theme_and_keeps_it(memory_store, native, launch):
    memory_store.set_value(None, "theme", "qdark")
    launch()
    assert appearance.qdarkstyleApplied() is not native
    assert memory_store.value(None, "theme", str) == "qdark"


@pytest.fixture
def window(main_window, local_series_settings):
    local_series_settings(main_window)
    return main_window


def _store(window):
    return window.series._settingsStore()


@pytest.mark.parametrize("platform, dev", [STABLE, MAC_DEV])
@pytest.mark.parametrize("theme", [appearance.SYSTEM, appearance.LIGHT, appearance.DARK])
def test_apply_theme_stores_nothing(window, build, platform, dev, theme):
    build(platform, dev)
    assert not _store(window).contains(None, "theme")
    assert window.applyTheme(theme)
    assert not _store(window).contains(None, "theme")


def test_reading_the_theme_for_the_launch_stores_nothing(window):
    assert not _store(window).contains(None, "theme")
    assert window.series.getOption("theme", write_default=False) == appearance.SYSTEM
    assert not _store(window).contains(None, "theme")
    # the ordinary read still fills the default in, as every other option does
    assert window.series.getOption("theme") == appearance.SYSTEM
    assert _store(window).contains(None, "theme")


@pytest.mark.parametrize("platform, dev", [STABLE, MAC_DEV])
def test_set_theme_still_stores_the_choice(window, build, platform, dev):
    build(platform, dev)
    window.setTheme(appearance.DARK)
    assert _store(window).value(None, "theme", str) == appearance.DARK
    window.setTheme(appearance.SYSTEM)
    assert _store(window).value(None, "theme", str) == appearance.SYSTEM

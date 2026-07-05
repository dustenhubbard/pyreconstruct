"""GUI-free settings storage for the core data model (M11 seam).

`Series` reads and writes user options through a `SettingsStore` rather than
touching `QSettings` directly, so the data model no longer depends on Qt/GUI
for settings access. GUI callers get the `QSettingsStore` default, whose
behavior is identical to the previous direct `QSettings` usage; headless
callers and tests can inject `DictSettingsStore` (pure Python, no Qt).

Two scopes are preserved exactly, matching the prior `QSettings` usage:
  - per-series settings, keyed by the series ``code`` (org ``"KHLab"``, app
    ``"PyReconstruct-{code}"``)
  - global settings (org ``"KHLab"``, app ``"PyReconstruct"``)

Pass ``code=None`` to address the global scope; pass a series ``code`` to
address that series' per-series scope.
"""

from abc import ABC, abstractmethod
from typing import Optional


class SettingsStore(ABC):
    """Minimal get/set interface over per-series and global settings.

    ``code=None`` selects the global scope; a non-``None`` ``code`` selects
    that series' per-series scope.
    """

    @abstractmethod
    def contains(self, code: Optional[str], key: str) -> bool:
        """Return True if ``key`` is stored in the given scope."""

    @abstractmethod
    def value(self, code: Optional[str], key: str, value_type: type):
        """Return the stored value for ``key`` in the given scope."""

    @abstractmethod
    def set_value(self, code: Optional[str], key: str, value) -> None:
        """Store ``value`` under ``key`` in the given scope."""


class QSettingsStore(SettingsStore):
    """Default store backed by ``QSettings`` (identical to prior behavior).

    This is the Qt adapter layer, so it imports ``QSettings`` -- lazily, so
    that importing this module and using ``DictSettingsStore`` require no Qt.
    A fresh ``QSettings`` is created per operation, exactly as before.
    """

    ORG = "KHLab"
    APP = "PyReconstruct"

    def _settings(self, code: Optional[str]):
        from PySide6.QtCore import QSettings
        app = self.APP if code is None else f"{self.APP}-{code}"
        return QSettings(self.ORG, app)

    def contains(self, code, key):
        return self._settings(code).contains(key)

    def value(self, code, key, value_type):
        return self._settings(code).value(key, type=value_type)

    def set_value(self, code, key, value):
        self._settings(code).setValue(key, value)


class DictSettingsStore(SettingsStore):
    """In-memory store for headless use and tests (pure Python, no Qt).

    Values round-trip as stored; ``value_type`` is accepted for interface
    parity but not used to coerce, since callers store the values they read
    back.
    """

    def __init__(self):
        # one namespace per scope: None (global) or a series code
        self._data = {}

    def _scope(self, code: Optional[str]) -> dict:
        return self._data.setdefault(code, {})

    def contains(self, code, key):
        return key in self._scope(code)

    def value(self, code, key, value_type):
        return self._scope(code).get(key)

    def set_value(self, code, key, value):
        self._scope(code)[key] = value

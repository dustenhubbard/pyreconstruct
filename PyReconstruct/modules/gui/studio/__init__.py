"""The "Studio" layout — the v1.30 UI overhaul's foundation.

A self-contained set of bespoke Qt widgets implementing the Studio / Atlas
layout grammar from the canonical spec (activity rail · first-class Objects
panel · dark canvas with glassy floating controls · flush tool rail ·
trace-palette strip · mono status bar), composed by :class:`~.shell.StudioShell`.

These are a pure **view layer**: they import only PySide6 and the theme/icon
utilities, take their content through plain-data setters, and announce user
intent through signals. They hold no reference to the field, series, or any
heavy runtime, so they construct headlessly, render offscreen for sign-off, and
can be adopted incrementally by the main window (which feeds them real data).

The one interactive accent is teal (``#37c0a6``); the EM canvas — and the
controls floating over it — stay dark in both Studio and Atlas. All chrome
color comes from :func:`PyReconstruct.modules.gui.utils.theme.studio_tokens`.
"""

from .shell import StudioShell

__all__ = ["StudioShell"]

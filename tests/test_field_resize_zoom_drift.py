"""Widget resizes must not move the field's magnification.

resizeWindow's aspect fixer only ever GROWS a view dimension, so shrinking
the field widget (collapsing the lists, narrowing the main window) zoomed
the view out a little, and every grow-then-shrink cycle drifted outward
forever. Long reported on window resizes; the lists collapse made it a
one-keystroke reproducer (his click test, 2026-08-25).

The fix scales the view window by the exact pixel change on every widget
resize, centered, so magnification holds and a cycle returns to the start.
Driven through the REAL field widget's resizeEvent on the real main window.
"""

import pytest

pytestmark = pytest.mark.gui


def _resize(field, w, h):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    old = QSize(*field.pixmap_dim)
    field.resizeEvent(QResizeEvent(QSize(w, h), old))


def test_collapse_expand_cycle_returns_the_exact_window(qapp, main_window, gui_dialogs):
    field = main_window.field
    w0, h0 = field.pixmap_dim
    start = list(field.series.window)

    _resize(field, w0 + 300, h0)     # the lists collapse: field gets wider
    _resize(field, w0, h0)           # the lists come back

    end = field.series.window
    for a, b in zip(start, end):
        assert a == pytest.approx(b, abs=1e-9)


def test_shrinking_keeps_the_magnification(qapp, main_window, gui_dialogs):
    field = main_window.field
    w0, h0 = field.pixmap_dim
    mag_before = field.series.window[2] / w0

    _resize(field, w0 - 250, h0 - 100)

    w1, _ = field.pixmap_dim
    mag_after = field.series.window[2] / w1
    assert mag_after == pytest.approx(mag_before, rel=1e-9)


def test_ten_cycles_do_not_drift(qapp, main_window, gui_dialogs):
    """The report was SLOW drift: one cycle looked fine, ten did not."""
    field = main_window.field
    w0, h0 = field.pixmap_dim
    start_w = field.series.window[2]

    for _ in range(10):
        _resize(field, w0 + 300, h0 + 80)
        _resize(field, w0, h0)

    assert field.series.window[2] == pytest.approx(start_w, rel=1e-9)

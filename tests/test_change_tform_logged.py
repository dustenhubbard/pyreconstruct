"""Transform changes log the current section without requiring a Qt widget."""

from types import SimpleNamespace

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.main import field_widget_4_data as fw


def test_change_tform_is_logged():
    calls = []
    field = SimpleNamespace(
        section=SimpleNamespace(n=7, align_locked=False, tform=Transform.identity()),
        series=SimpleNamespace(addLog=lambda *args: calls.append(args)),
        propagate_tform=False,
        tform_before_change=None,
        generateView=lambda: None,
        saveState=lambda: None,
    )

    fw.FieldWidgetData.changeTform(field, Transform([1, 0, 12, 0, 1, -8]))

    assert calls == [(None, field.section.n, "Modify transform")]

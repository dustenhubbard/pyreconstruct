"""The "Images not found" prompt offers Yes as its default button.

`QMessageBox.question(parent, title, text, buttons, defaultButton)` reads its
fourth and fifth positional arguments as the button set and the default. The
prompt passed `Yes, No` there, so No was the default: the blue button, and the
one Return pressed.
"""

import pytest
from PySide6.QtWidgets import QMessageBox

pytestmark = pytest.mark.gui


def test_images_not_found_defaults_to_yes(main_window, monkeypatch):
    calls = []

    def question(*args, **kwargs):
        calls.append((args, kwargs))
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))

    main_window.changeSrcDir(notify=True)

    [(args, kwargs)] = calls
    assert args[1] == "Images Not Found"
    buttons = kwargs.get("buttons", args[3] if len(args) > 3 else None)
    default = kwargs.get("defaultButton", args[4] if len(args) > 4 else None)
    assert buttons == QMessageBox.Yes | QMessageBox.No
    assert default == QMessageBox.Yes

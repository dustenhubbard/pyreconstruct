"""Help > Class documents opens the class pages on pyreconstruct.org.

The row is built once in ``main/menubar.py``, under Online resources beside the
user guide. The macOS menu bar reuses the same ``openclass_act`` action
(``mac_menubar.HELP_ROWS``).
"""

from PyReconstruct.modules.gui.main.menubar import return_menubar
from PyReconstruct.modules.gui.main.mac_menubar import HELP_ROWS

CLASS_PAGES = "https://pyreconstruct.org/class/"


class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _Series(_Anything):
    def getOption(self, name, get_default=False):
        return [] if name == "recently_opened_series" else ""


def _find(items, attr):
    for item in items:
        if isinstance(item, tuple) and item[0] == attr:
            return item
        if isinstance(item, dict):
            found = _find(item["opts"], attr)
            if found is not None:
                return found
    return None


def _menubar(opened):
    series = _Series(
        jser_fp="/nonexistent/current.jser",
        object_groups=_Anything(groups={}),
        groups_visibility={},
        user_columns={},
        alignments=set(),
        _local_store=None,
    )
    window = _Anything(series=series, field=_Anything(), mouse_palette=_Anything())
    window.openWebsite = opened.append
    return return_menubar(window)


def test_class_documents_row_opens_the_class_pages():
    opened = []
    row = _find(_menubar(opened), "openclass_act")
    assert row is not None and row[1] == "Class documents"
    row[3]()
    assert opened == [CLASS_PAGES]


def test_class_documents_sits_under_the_user_guide():
    online = _find_menu(_menubar([]), "onlinemenu")
    attrs = [item[0] for item in online["opts"] if isinstance(item, tuple)]
    assert attrs.index("openclass_act") == attrs.index("openwiki_act") + 1


def test_macos_help_menu_shows_the_same_row():
    assert HELP_ROWS.index("openclass_act") == HELP_ROWS.index("openwiki_act") + 1


def _find_menu(items, attr):
    for item in items:
        if isinstance(item, dict):
            if item["attr_name"] == attr:
                return item
            found = _find_menu(item["opts"], attr)
            if found is not None:
                return found
    return None

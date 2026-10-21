"""Help > PyReconstruct user guide opens the website guide, not the GitHub wiki.

The row is built once in ``main/menubar.py``; the macOS menu bar reuses the same
``openwiki_act`` action (``mac_menubar.HELP_ROWS``), so pinning the callback here
covers every platform's menu bar.
"""

from PyReconstruct.modules.gui.main.menubar import return_menubar
from PyReconstruct.modules.gui.main.mac_menubar import HELP_ROWS

SITE_GUIDE = "https://pyreconstruct.org/USER_GUIDE/"


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


def test_user_guide_row_opens_the_website_guide():
    opened = []
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

    row = _find(return_menubar(window), "openwiki_act")
    assert row is not None and row[1] == "PyReconstruct user guide"
    row[3]()
    assert opened == [SITE_GUIDE]


def test_macos_help_menu_reuses_the_same_row():
    assert "openwiki_act" in HELP_ROWS

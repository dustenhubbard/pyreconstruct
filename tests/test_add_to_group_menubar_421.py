"""Adding many objects to a new group rebuilds the menubar once (fork #421).

The report: adding many objects to a group sat for up to a minute with nothing
on screen. `addToGroup` rebuilt the whole menubar once per selected object when
the group was new, 20 to 30 ms each, so 2,000 objects took 43 seconds. Rebuilding
it once after the loop takes that to 0.6 seconds, nothing that needs a bar.
"""
import pytest

from PyReconstruct.modules.gui.main import field_widget_3_object as fw3

pytestmark = pytest.mark.gui


def _add(main_window, monkeypatch, names, group):
    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return group, True

    monkeypatch.setattr(fw3, "ObjectGroupDialog", Dialog)
    field = main_window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(names))

    rebuilds = []
    real = main_window.createMenuBar

    def counting(*args, **kwargs):
        rebuilds.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window, "createMenuBar", counting)
    field.addToGroup()
    return len(rebuilds)


def test_new_group_rebuilds_the_menubar_once(main_window, monkeypatch):
    series = main_window.series
    names = sorted(series.data["objects"].keys())
    assert len(names) > 2, "fixture series has too few objects"
    assert "issue421_group" not in series.object_groups.getGroupList()

    rebuilds = _add(main_window, monkeypatch, names, "issue421_group")

    assert rebuilds == 1
    assert series.object_groups.getGroupObjects("issue421_group") == set(names)
    assert series.groups_visibility["issue421_group"] is True


def test_existing_group_does_not_rebuild_the_menubar(main_window, monkeypatch):
    series = main_window.series
    names = sorted(series.data["objects"].keys())
    series.object_groups.add(group="issue421_group", obj=names[0])
    series.groups_visibility["issue421_group"] = True

    rebuilds = _add(main_window, monkeypatch, names[1:], "issue421_group")

    assert rebuilds == 0
    assert series.object_groups.getGroupObjects("issue421_group") == set(names)

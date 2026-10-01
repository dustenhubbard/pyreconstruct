"""`To Neuroglancer (Zarr)...` passes the group padding on (fork #602).

``exportToZarr`` read ``Group padding (px):`` from the dialog and then left it
out of the command, so ``create_ng_zarr.py`` always used its default of 50.
"""

import subprocess

import pytest

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("max_tissue", [True, False])
def test_padding_reaches_the_script(
    main_window, main_window_dialogs, monkeypatch, tmp_path, max_tissue
):
    from PyReconstruct.assets.scripts.create_ng_zarr import parser
    from PyReconstruct.modules.gui.main import main_window as mw

    launched = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **kw: launched.append(cmd) or None,
    )
    ## the dask check would prompt; it is not what this test is about
    monkeypatch.setattr(mw, "modules_available", lambda *a, **k: True)

    sections = sorted(main_window.series.sections)
    groups = main_window.series.object_groups.getGroupList()[:1]
    main_window_dialogs.responses.append((
        [sections[1], sections[-1], 200, groups, [("Export all tissue", max_tissue)]],
        True,
    ))
    main_window_dialogs.file_responses.append(str(tmp_path / "out.zarr"))

    main_window.exportToZarr()

    assert len(launched) == 1
    ## the script's own parser reads what follows the jser path
    cmd = launched[0]
    script_args = cmd[cmd.index("create_ng_zarr") + 1:]
    monkeypatch.setattr("sys.argv", ["create_ng_zarr.py", *script_args])
    assert parser.parse_args(parser.get_args())[5] == 200

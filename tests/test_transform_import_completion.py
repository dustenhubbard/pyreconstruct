"""What the window does after `Import alignments > From .txt file...` and
`From SWiFT project...`.

Both imports end the same way once the import returns: reload the section,
rebuild the tables, then rebuild the alignment menus if the names changed,
and only then show the success notice. `MainWindow._finishTransformImport`
holds those steps for both. A canceled or failed import runs none of them.

The steps are recorded by wrapping the real methods on a live `MainWindow`,
so each one still does its work.
"""

import json

import pytest


def _write_tforms(series, path):
    with open(path, "w") as f:
        for snum in sorted(series.sections):
            f.write(f"{snum} 1 0 0 0 1 0\n")
    return str(path)


def _write_swift(path, n):
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    level = {"swim_settings": {"img_size": [100, 100]}, "alt_cafm": identity}
    stack = [{"levels": {"s1": level}} for _ in range(n)]
    with open(path, "w") as f:
        json.dump({"level_data": {"s1": {}}, "stack": stack}, f)
    return str(path)


SWIFT_SCALE_1 = (["1", [("Includes cal grid", False)]], True)


@pytest.fixture
def steps(main_window, main_window_dialogs, monkeypatch):
    """Record the completion steps and the notices, in call order."""
    from PyReconstruct.modules.gui.main import main_window as mw

    window = main_window
    calls = []

    def record(name, real):
        def wrapper(*args, **kwargs):
            calls.append((name, args))
            return real(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(
        window.field, "reload", record("reload", window.field.reload)
    )
    table_manager = window.field.table_manager
    monkeypatch.setattr(
        table_manager, "recreateTables",
        record("recreateTables", table_manager.recreateTables)
    )
    monkeypatch.setattr(
        window, "refreshAlignmentActions",
        record("refreshAlignmentActions", window.refreshAlignmentActions)
    )
    monkeypatch.setattr(
        mw, "notify", record("notify", main_window_dialogs.notify)
    )
    return calls


def _names(calls):
    return [name for name, _ in calls]


@pytest.mark.gui
def test_txt_import_runs_the_completion_steps_in_order(
    main_window, steps, tmp_path
):
    window = main_window
    before = set(window.series.alignments)

    window.importTransforms(_write_tforms(window.series, tmp_path / "t.txt"))

    assert _names(steps) == [
        "reload", "recreateTables", "refreshAlignmentActions", "notify"
    ]
    assert steps[2][1] == (before,)
    assert steps[3][1] == ("Transforms imported successfully.",)
    assert window.series.alignment not in before


@pytest.mark.gui
def test_txt_import_canceled_at_the_file_dialog_runs_no_steps(
    main_window, steps
):
    # no scripted file response: the dialog returns "" as a cancel does
    main_window.importTransforms()

    assert steps == []


@pytest.mark.gui
def test_txt_import_that_fails_runs_no_completion_steps(
    main_window, steps, tmp_path
):
    bad_fp = tmp_path / "bad.txt"
    bad_fp.write_text("not a transform\n")

    main_window.importTransforms(str(bad_fp))

    assert _names(steps) == ["notify"]
    assert steps[0][1][0].startswith("No transforms were imported.")


@pytest.mark.gui
def test_swift_import_runs_the_completion_steps_in_order(
    main_window, main_window_dialogs, steps, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    main_window_dialogs.responses.append(SWIFT_SCALE_1)

    window.importSwiftTransforms(
        _write_swift(tmp_path / "p.json", len(window.series.sections))
    )

    assert _names(steps) == [
        "reload", "recreateTables", "refreshAlignmentActions", "notify"
    ]
    assert steps[2][1] == (before,)
    assert steps[3][1][0].startswith("Transforms imported successfully.")
    assert window.series.alignment not in before


@pytest.mark.gui
def test_swift_import_canceled_at_the_scale_dialog_runs_no_steps(
    main_window, main_window_dialogs, steps, tmp_path
):
    window = main_window
    # no scripted response: the scale dialog returns as a cancel does
    window.importSwiftTransforms(
        _write_swift(tmp_path / "p.json", len(window.series.sections))
    )

    assert main_window_dialogs.dialogs == ["Import SWiFT Transforms"]
    assert steps == []


@pytest.mark.gui
def test_swift_import_that_fails_runs_no_completion_steps(
    main_window, main_window_dialogs, steps, tmp_path
):
    window = main_window
    main_window_dialogs.responses.append(SWIFT_SCALE_1)

    window.importSwiftTransforms(
        _write_swift(tmp_path / "p.json", len(window.series.sections) - 1)
    )

    assert _names(steps) == ["notify"]
    assert steps[0][1][0].startswith("No transforms were imported.")

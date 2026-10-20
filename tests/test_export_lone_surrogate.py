"""Text exports finish when a name holds a lone surrogate.

A lone surrogate is half of a UTF-16 pair with no other half. An old or
damaged file can hold one in an object or trace name. Strict encoding has no
bytes for it, so an export that wrote the name raised. The exports now write it
as the text ``\\ud800``, as the log history export does.

The username is never assigned through ``series.user``: its setter writes the
real ``username`` setting. The tests patch the property on the class instead.
"""
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.ztrace import Ztrace

from tests.test_crop_zarr_cli import OBJECT, RADIUS, case  # noqa: F401  (fixture)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "dev" / "assets" / "checker" / "files" / "shapes1.jser"
)

NAME = "axon_\ud800_1"
ESCAPED = "axon_\\ud800_1"


def open_series(fp):
    s = Series.openJser(str(fp), progress=NullProgressReporter,
                        notifier=NullNotifier())
    s.setSettingsStore(DictSettingsStore())
    return s


@pytest.fixture(autouse=True)
def no_real_username(monkeypatch):
    monkeypatch.setattr(Series, "user", property(lambda self: "alice"))


@pytest.fixture
def series(tmp_path):
    if not FIXTURE.exists():
        pytest.skip("fixture shapes1.jser not found")
    fp = tmp_path / "a" / "shapes1.jser"
    fp.parent.mkdir()
    shutil.copyfile(FIXTURE, fp)
    s = open_series(fp)
    old = sorted(s.data["objects"])[0]
    s.editObjectAttributes([old], name=NAME)
    yield s
    s.leave_open = False
    s.close()


def written(fp):
    return Path(fp).read_bytes().decode("utf-8")  # strict: valid UTF-8


def test_the_object_list_csv_writes_the_name_as_text(series, tmp_path):
    out = tmp_path / "objects.csv"
    series.exportObjectsCSV(out)
    assert ESCAPED in written(out)


def test_the_trace_csv_writes_the_name_as_text(series, tmp_path):
    out = tmp_path / "traces.csv"
    series.data.exportTracesCSV(str(out))
    assert ESCAPED in written(out)


def test_the_palette_csv_writes_the_name_as_text(series, tmp_path):
    series.palette_traces[series.palette_index[0]][0].name = NAME
    out = tmp_path / "palette.csv"
    series.exportTracePaletteCSV(str(out))
    assert ESCAPED in written(out)


def test_the_ztrace_csv_writes_the_name_as_text(series, tmp_path):
    snum = min(series.sections)
    series.ztraces[NAME] = Ztrace(NAME, (255, 0, 0), [(1.0, 1.0, snum)])
    out = tmp_path / "ztraces.csv"
    series.exportZtracesCSV(out)
    assert ESCAPED in written(out)


def test_the_3d_data_csv_writes_the_name_as_text(qapp, series, tmp_path, monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
    series.setAttr(NAME, "3D_mode", "surface")
    out = tmp_path / "3d.csv"
    ev.export3DData(series, [NAME], str(out))
    assert ESCAPED in written(out)


def test_the_xml_export_writes_the_names_as_text(qapp, series, tmp_path):
    from PyReconstruct.modules.backend.func.xml_json_conversions import jsonToXML
    snum = min(series.sections)
    series.palette_traces[series.palette_index[0]][0].name = NAME
    series.ztraces[NAME] = Ztrace(NAME, (255, 0, 0), [(1.0, 1.0, snum)])
    out = tmp_path / "xml"
    out.mkdir()
    jsonToXML(series, str(out))
    assert written(out / f"{series.name}.ser").count(ESCAPED) == 2
    sections = [written(fp) for fp in out.glob(f"{series.name}.[0-9]*")]
    assert any(ESCAPED in text for text in sections)


def test_the_crop_log_writes_the_name_as_text(case, tmp_path):  # noqa: F811  (fixture)
    from PyReconstruct.modules.backend.crop_zarr import cropSections, resolvePaths
    jser, src = case
    s = open_series(jser)
    s.editObjectAttributes([OBJECT], name=NAME)
    s.save()
    out_fp, src_group, scales = resolvePaths(s, NAME, "", str(tmp_path / "crop.zarr"))
    try:
        log_fp = cropSections(s, NAME, RADIUS, src_group, scales, out_fp,
                              show_progress=False, echo=lambda line: None)
        assert ESCAPED in written(log_fp)
    finally:
        s.leave_open = False
        s.close()

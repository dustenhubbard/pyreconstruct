"""Invalid and conflicting stored IDs must not discard trace data."""

import json
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import keyed_trace_row_from_positional
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.trace_id import (
    decodeTraceID,
    deriveTraceID,
    encodeTraceID,
)


ROW = [[1.0, 2.0, 3.0], [2.0, 4.0, 2.0], [255, 0, 0],
       True, False, False, ["none", "none"], ["tag"]]
INVALID_IDS = [
    123, 12.5, True, False, None, [], ["A"] * 11, {},
    {str(i): "A" for i in range(11)}, ["AAAAAAAAAAA"], "bad-id",
]


def _write_series(tmp_path, ids, same_section=False):
    source = Path(__file__).parent / "fixtures" / "parity_series.jser"
    document = json.loads(source.read_text())
    document["sections"] = document["sections"][:2]
    for section in document["sections"]:
        section["contours"] = {}
    for n, (name, trace_id) in enumerate(zip(("axon", "dendrite01"), ids)):
        section = document["sections"][0 if same_section else n]
        section["contours"][name] = [
            keyed_trace_row_from_positional(ROW, trace_id, "fill_mode")
        ]
    path = tmp_path / "recovery.jser"
    path.write_text(json.dumps(document))
    return path


def _read_traces(series):
    result = {}
    for n in sorted(series.sections):
        section = series.loadSection(n)
        for name, contour in section.contours.items():
            assert len(contour) == 1
            trace = contour[0]
            assert trace.getList(include_name=False) == ROW
            result[name] = section._columns.getID(section._column_rows[trace])
    assert set(result) == {"axon", "dendrite01"}
    return result


@pytest.mark.parametrize("trace_id", INVALID_IDS)
def test_decode_rejects_invalid_json_id_with_value_error(trace_id):
    with pytest.raises(ValueError):
        decodeTraceID(trace_id)


@pytest.mark.parametrize("trace_id", INVALID_IDS)
def test_invalid_stored_id_keeps_traces_and_derives_identity(tmp_path, trace_id):
    preserved = encodeTraceID(42)
    path = _write_series(tmp_path, [trace_id, preserved])
    original = path.read_bytes()
    series = Series.openJser(str(path), progress=NullProgressReporter)
    try:
        ids = _read_traces(series)
        assert ids["dendrite01"] == preserved
        assert ids["axon"] == deriveTraceID(0, "axon", ROW)
        decodeTraceID(ids["axon"])
        if trace_id is not None:
            assert (trace_id, "axon") in series.trace_id_issuer.malformed
    finally:
        series.close()
    assert path.read_bytes() == original


@pytest.mark.parametrize("same_section", [False, True])
def test_duplicate_stored_id_warns_about_replaced_trace(tmp_path, capsys, same_section):
    duplicate = encodeTraceID(42)
    path = _write_series(tmp_path, [duplicate, duplicate], same_section)
    original = path.read_bytes()
    series = Series.openJser(str(path), progress=NullProgressReporter)
    try:
        warning = capsys.readouterr().err
        assert "WARNING" in warning
        assert duplicate in warning
        assert "dendrite01" in warning
        assert f"section {0 if same_section else 1}" in warning
        ids = _read_traces(series)
        assert ids["axon"] == duplicate
        assert ids["dendrite01"] != duplicate
        decodeTraceID(ids["dendrite01"])
        assert (duplicate, "dendrite01") in series.trace_id_issuer.collisions
    finally:
        series.close()
    assert path.read_bytes() == original

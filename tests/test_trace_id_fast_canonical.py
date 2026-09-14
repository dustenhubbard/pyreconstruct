"""The tid-v1 canonical text, produced fast, is the same text.

Opening a 249 MB lab series took 16.8 s, and 7.4 s of it was json.dumps
building the canonical text of 99,207 trace rows, twice each (once for the
issuer's record, once for the hash). canonicalJSON hands the work to orjson
where its bytes provably match and falls back to json where they do not, and
deriveForSection now serializes each row once. The ids must not move: these
tests pin the parity, the fallback cases, and the one-serialization payload.
"""
import json

import pytest

from PyReconstruct.modules.datatypes import trace_id
from PyReconstruct.modules.datatypes.trace_id import (
    TraceIDIssuer, canonicalJSON, deriveTraceID,
)


def reference(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


ROWS = [
    [[0.5, 1.25, 2.0], [0.1, 0.2, 0.30000000000000004], [255, 128, 64], True, False, False, ["none", "none"], []],
    [[1e16, -0.0, 1e22, 5e-324, 123456789012345680.0], [0.0001, 0.00012, 1234.5], [0, 0, 0], False, True, False, ["solid", "always"], ["axon", "tag two"]],
    [[1e-05, 3.5e-05], [0.001], [1, 2, 3], True, False, False, ["none", "none"], []],          # tiny floats: json says 1e-05
    [[-0.00001, 7.0], [0.0], [1, 2, 3], True, False, False, ["none", "none"], []],           # negative tiny float
    [[1.0], [2.0], [9, 9, 9], True, False, False, ["none", "none"], ["café", "→"]],      # non-ASCII tags
    [[1.0], [2.0], [9, 9, 9], True, False, False, ["none", "none"], ["tab\tnew\nline", "quote\"back\\slash", "\x01\x1f\x7f"]],
    [[1.0], [2.0], [9, 9, 9], True, False, False, ["none", "none"], ["0.0000 in a string", "1e-05 in a string"]],
    [[4.8969352046225824e-08, -5.137716631876371e-06, 2.9e-09], [1.5e300, 1e16], [1, 2, 3], True, False, False, ["none", "none"], []],  # json pads the exponent: e-08
    [[1.0], [2.0], [9, 9, 9], True, False, False, ["none", "none"], ["del\x7fchar"]],  # json escapes DEL, orjson does not
]


@pytest.mark.parametrize("row", ROWS)
def test_canonical_text_matches_the_frozen_contract(row):
    assert canonicalJSON(row) == reference(row)
    payload = ["tid-v1", 12, "d01sp01", row]
    assert canonicalJSON(payload) == reference(payload)


@pytest.mark.parametrize("value", [1e-05, 3.5e-05, -1e-05, 4.9e-08, -5.1e-06, "\x7f", "café", "→", ["x", 1e-07]])
def test_the_known_divergences_fall_back_to_json(value):
    assert canonicalJSON(value) == reference(value)


def test_names_with_non_ascii_and_tiny_coordinates_still_hash_identically():
    row = ROWS[2]
    with_fast = deriveTraceID(3, "δ-cell", row)
    trace_id._HAVE_ORJSON, saved = False, trace_id._HAVE_ORJSON
    try:
        with_json = deriveTraceID(3, "δ-cell", row)
    finally:
        trace_id._HAVE_ORJSON = saved
    assert with_fast == with_json


@pytest.mark.parametrize("row", ROWS)
def test_the_prebuilt_row_text_gives_the_same_id(row):
    plain = deriveTraceID(7, "d01sp01", row)
    prebuilt = deriveTraceID(7, "d01sp01", row, row_json=canonicalJSON(row))
    assert prebuilt == plain


def test_a_whole_section_derives_the_same_ids_with_and_without_orjson():
    contours = {"d01sp01": ROWS[:3], "axon": ROWS[3:], "café": ROWS[:2]}
    fast = TraceIDIssuer().deriveForSection(5, contours)
    assert len(fast) == sum(len(v) for v in contours.values())
    saved = trace_id._HAVE_ORJSON
    trace_id._HAVE_ORJSON = False
    try:
        slow = TraceIDIssuer().deriveForSection(5, contours)
    finally:
        trace_id._HAVE_ORJSON = saved
    assert fast == slow

"""The ``autoseg`` options bag is kept as it is, deliberately.

Two separate .jser audits have filed "``autoseg`` options are never pruned, so
stale job parameters persist". It is accepted rather than fixed, and this file
pins the decision so a third audit finds a failing test rather than an open
question. The reasoning is written out at the ``"autoseg"`` entry in
``Series.getEmptyDict``; in short:

  * the three dialogs read the bag only to prefill their fields, so reuse is
    the feature;
  * the writers set a fixed 17 keys between them, so it cannot grow without
    bound (about 400 bytes fully populated);
  * every writer has been commented out since 2024, so nothing accumulates
    today at all.

Pruning would save a few hundred bytes in old files and discard the parameters
the dialogs want back if autosegmentation returns.
"""
import json

from PyReconstruct.modules.datatypes.series import Series

#: The union of the three dicts the (commented-out) train, predict and segment
#: paths in ``gui/main/main_window.py`` write into ``options["autoseg"]``.
FULL_BAG = {
    "zarr_current": "/data/series/data.zarr",
    "iters": 100000,
    "save_every": 2000,
    "group": "seg_001",
    "model_path": "/opt/autoseg/models/setup01/model.py",
    "checkpts_dir": "/data/series/checkpoints",
    "pre_cache": [10, 40],
    "min_masked": 0.1,
    "downsample_bool": True,
    "write": "affs",
    "increase": [0, 0, 0],
    "full_out_roi": False,
    "thresholds": [0.1, 0.5, 0.9],
    "downsample_int": 1,
    "norm_preds": True,
    "min_seed": 10,
    "merge_fun": "mean",
}


def test_updateJSON_keeps_every_autoseg_key():
    """Loading an old series does not drop parameters from a previous job."""
    series_data = Series.getEmptyDict()
    series_data["options"]["autoseg"] = dict(FULL_BAG)

    Series.updateJSON(series_data)

    assert series_data["options"]["autoseg"] == FULL_BAG


def test_unknown_option_keys_are_still_pruned():
    """The retention is specific to `autoseg`'s contents, not to `options`.

    ``updateJSON`` does drop option keys it has no concept of. That is what
    makes the `autoseg` bag a deliberate exception rather than an oversight in
    the same pass.
    """
    series_data = Series.getEmptyDict()
    series_data["options"]["some_option_from_a_future_build"] = 1

    Series.updateJSON(series_data)

    assert "some_option_from_a_future_build" not in series_data["options"]


def test_full_bag_is_small():
    """The cost of keeping it is a few hundred bytes, not unbounded growth."""
    assert len(json.dumps(FULL_BAG, separators=(",", ":"))) < 1024

"""``Series.updateJSON`` repairs a saved window with a zero height.

A series file stores ``window`` as ``[x, y, w, h]``. On load a zero width or
height is set to 1.
"""
from PyReconstruct.modules.datatypes.series import Series


def test_updatejson_sets_a_zero_height_window_to_one():
    sd = Series.getEmptyDict()
    sd["window"] = [10, 20, 5, 0]
    Series.updateJSON(sd)
    assert sd["window"] == [10, 20, 5, 1]

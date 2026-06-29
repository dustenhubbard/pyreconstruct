"""Regression test for ImportWidget.accept accumulating stale responses.

ImportWidget.responses is created once and accept() only appended to it.
ImportSeriesDialog.accept validates its widget tabs in order and re-opens on a
failure, so a widget whose tab precedes a failing one had accept() run again on
re-submit -- doubling its responses list. Downstream consumers index from the
front, so they then read the stale first-submission values instead of the
corrected ones. Reset the accumulator at the start of accept().
"""
import types

from PyReconstruct.modules.gui.dialog import import_series as imp


class _Input:
    def __init__(self, value, valid=True):
        self.value = value
        self.valid = valid

    def getResponse(self):
        return (self.value, self.valid)


def test_accept_does_not_accumulate_across_resubmits():
    stub = types.SimpleNamespace(inputs=[_Input("a"), _Input("b")], responses=[])

    assert imp.ImportWidget.accept(stub) is True
    assert stub.responses == ["a", "b"]

    # simulate a re-submit (a later tab failed validation the first time)
    assert imp.ImportWidget.accept(stub) is True
    assert stub.responses == ["a", "b"], "responses must not double on re-submit"


def test_accept_returns_false_on_invalid_input():
    stub = types.SimpleNamespace(
        inputs=[_Input("a"), _Input(None, valid=False)], responses=[]
    )

    assert imp.ImportWidget.accept(stub) is False

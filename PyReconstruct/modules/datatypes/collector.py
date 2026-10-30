"""The cyclic garbage collector while a series is open in the window.

An open leaves millions of objects that live as long as the series (about
2.9 million for a 550,000-trace series). Python's full collection walks all of
them each time, about 1 s on that series, and it came round every 4 to 10
section changes. After the open, `settleAfterOpen` collects once and freezes
what is left, so full collections skip the series' objects, and raises the
young-generation threshold so the freeze does not set off a full collection
about twice a section change. `restore` puts back the settings it found when
that series closes. Reference counting still frees everything as before.

Objects frozen at the open are never collected while the series stays open: a
cycle among them that later becomes garbage stays in memory until the close.
So a series that closed but is still held when the next one settles (by a
3D scene, a plugin or a dialog) is not frozen with it: the freeze waits until
a collection frees that series.
"""

import gc
import weakref

YOUNG_THRESHOLD = 10000

# (series, the thresholds before it settled), or None when nothing is settled
_settled = None

# a weak reference to the series restored last, until the next settle
_closed = None


def settleAfterOpen(series):
    """Collect, freeze what is left and raise the young threshold for series.

    A series settled before it is restored first.
    """
    global _settled, _closed
    if _settled is not None:
        restore(_settled[0])
    before = gc.get_threshold()
    gc.collect()
    if _closed is not None and _closed() is not None:
        # frozen, the closed series could not be freed once its holder lets go
        gc.callbacks.append(_freezeWhenClosedFreed)
    else:
        gc.freeze()
        _closed = None
    gc.set_threshold(YOUNG_THRESHOLD, before[1], before[2])
    _settled = (series, before)


def _freezeWhenClosedFreed(phase, info):
    """After the collection that frees the closed series, freeze what is left."""
    global _closed
    if phase != "stop" or _closed() is not None:
        return
    gc.callbacks.remove(_freezeWhenClosedFreed)
    gc.freeze()
    _closed = None


def restore(series):
    """Unfreeze and put back the thresholds, if series is the one settled."""
    global _settled, _closed
    if _settled is None or _settled[0] is not series:
        return
    if _freezeWhenClosedFreed in gc.callbacks:
        gc.callbacks.remove(_freezeWhenClosedFreed)
    _closed = weakref.ref(series)
    gc.unfreeze()
    gc.set_threshold(*_settled[1])
    _settled = None


def settledSeries():
    """The series the collector is settled for, or None."""
    return None if _settled is None else _settled[0]

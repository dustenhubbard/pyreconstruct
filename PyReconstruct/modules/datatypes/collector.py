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
So while any series that closed is still held (by a 3D scene, a plugin or a
dialog), an open only collects: nothing is frozen and the thresholds stay as
they are, so that series is freed once its holder lets go. The next open
settles again.
"""

import gc
import weakref

YOUNG_THRESHOLD = 10000

# (series, the thresholds before it settled), or None when nothing is settled
_settled = None

# weak references to every series restored, dropped once that series is freed
_closed = []


def settleAfterOpen(series):
    """Collect, freeze what is left and raise the young threshold for series.

    A series settled before it is restored first. While a closed series is
    still alive after the collection, nothing is frozen or raised.
    """
    global _settled
    if _settled is not None:
        restore(_settled[0])
    before = gc.get_threshold()
    gc.collect()
    _closed[:] = [ref for ref in _closed if ref() is not None]
    if not _closed:
        gc.freeze()
        gc.set_threshold(YOUNG_THRESHOLD, before[1], before[2])
    _settled = (series, before)


def restore(series):
    """Unfreeze and put back the thresholds, if series is the one settled."""
    global _settled
    if _settled is None or _settled[0] is not series:
        return
    _closed.append(weakref.ref(series))
    gc.unfreeze()
    gc.set_threshold(*_settled[1])
    _settled = None


def settledSeries():
    """The series the collector is settled for, or None."""
    return None if _settled is None else _settled[0]

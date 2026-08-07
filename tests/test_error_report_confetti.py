"""The confetti burst on "Copy report to clipboard".

What this file can check and what it cannot are worth separating up front,
because the feature is an animation and most of what a reader would want checked
is visual.

CHECKED HERE: that a burst happens on a copy that worked and does not happen on
one that did not; that the particles are real child widgets, countable while
they fly; that every one of them is gone once the animation ends; that repeating
the click neither crashes nor accumulates widgets; that a particle passing over
the button does not swallow a click meant for it; that the "Copied ✓" label this
change shares a handler with still behaves exactly as it did; and that the burst
is actually *seen* -- that no particle leaves the window that clips it, and that
none is still opaque once it is below the height it was thrown from.

That last pair is geometry, not taste, and it is here because the burst failed
it once: parented to the window rather than the button, but thrown far enough
down that all 12 particles crossed the window's bottom edge at close to full
opacity, so the fade the module is built around happened where nothing could see
it. A test that only counts widgets cannot tell that apart from a working
animation.

NOT CHECKED HERE, and not by anything else: what it looks like. Colour, the
easing curve, how far the arc should throw, whether 12 dots reads as "small" or
as "too much" -- none of that is asserted, because none of it has a correct
value the suite could hold it to. It is a judgement about feel, and it is made
by looking at it. The tests below would pass on a burst that was the wrong
colour or that went sideways instead of up; they exist to stop the mechanical
failures around it (a leak, a crash, a burst on a failed copy, a broken label, a
burst drawn where it cannot be seen), not to say the animation is good.

The particle lifetime tests drive the event loop with `qtbot.wait`. That is not
a sleep for timing's sake: a `QPropertyAnimation` advances on the event loop and
`deleteLater` is delivered by it, so without a real wait the burst never runs
and nothing is ever collected. The waits allow generously more than
`DURATION_RANGE`'s ceiling.
"""

import random

import pytest

from PySide6.QtCore import QParallelAnimationGroup, Qt
from PySide6.QtWidgets import QWidget

from PyReconstruct.modules.gui.utils import errors
from PyReconstruct.modules.gui.utils.confetti import (
    ConfettiParticle,
    DURATION_RANGE,
    PARTICLE_COUNT,
    burst_confetti,
)

pytestmark = pytest.mark.gui


# Comfortably past the longest particle, with room for the deferred delete.
SETTLE_MS = DURATION_RANGE[1] + 400


def _dialog(qtbot):
    dialog = errors.ErrorReportDialog("<b>Something failed.</b>", "the report text")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    return dialog


def _particles(dialog):
    """Every particle currently alive under the dialog.

    `findChildren` walks the C++ object tree, so a particle that has been
    `deleteLater`-ed and collected is absent here; one merely scheduled for
    deletion is still present. That distinction is the point of the waits.
    """
    return dialog.findChildren(ConfettiParticle)


def _sweep(particle, step_ms=5):
    """Step one particle's own animation by hand, yielding `(pos, opacity)`.

    Driven rather than waited on. The geometry below is a function of the
    animation's progress, not of the clock, and sampling it off the event loop
    would make the assertions depend on how promptly the loop happened to tick.

    Two Qt details make this work. A `QPropertyAnimation` writes its target only
    while it is running, so the group is started and immediately paused rather
    than left stopped -- a stopped animation ignores `setCurrentTime` and the
    sweep would read the same frame every time. And the sweep stops one step
    short of the duration, because reaching the end of a live animation emits
    `finished`, which here means `deleteLater` on the widget being measured.
    """
    group = particle.findChild(QParallelAnimationGroup)
    assert group is not None, "every particle owns its animation group"
    group.start()
    group.pause()
    try:
        for elapsed in range(0, group.duration(), step_ms):
            group.setCurrentTime(elapsed)
            yield particle.pos(), particle.getOpacity()
    finally:
        group.stop()


class _NoClipboard:
    """Stands in for `QApplication` on a platform that has no clipboard.

    Patched over the name in `errors`, rather than over `QApplication.clipboard`
    itself: the real class is a C++ type whose attributes are not reliably
    settable, and `_copyReport` reaches the clipboard only through this name.
    """

    @staticmethod
    def clipboard():
        return None


def test_a_successful_copy_spawns_particles(qtbot):
    """The whole point: a copy that worked is celebrated."""
    dialog = _dialog(qtbot)
    assert _particles(dialog) == []

    dialog._copyReport()

    assert len(_particles(dialog)) == PARTICLE_COUNT


def test_the_particles_belong_to_the_window_not_to_the_button(qtbot):
    """A child widget is clipped to its parent, so the button cannot be it.

    Parented to the button, the burst would be invisible outside a rectangle a
    few pixels tall -- the animation would run and show nothing. This is the
    kind of mistake that looks fine in the source and produces no feature.
    """
    dialog = _dialog(qtbot)
    dialog._copyReport()

    particles = _particles(dialog)
    assert particles
    assert all(p.parent() is dialog for p in particles)
    assert not dialog._copy_btn.findChildren(ConfettiParticle)


def test_the_burst_stays_inside_the_window_it_is_drawn_on(qtbot):
    """Parenting to the window solves only half of the clipping problem.

    The window clips exactly as the button would, and the copy button sits about
    11px above the bottom of a bottom-anchored button row, so a fall of any real
    size takes the particle under the window's edge and Qt cuts it off there.
    The burst was measured doing precisely that: every one of the 12 particles
    below the bottom edge of a 720x480 dialog by t=500ms, which reads as the
    burst blinking out along a line rather than finishing.

    Several sizes, because resizing the dialog is not a fix and must not look
    like one -- the button row is anchored to the bottom at every size, so the
    clearance under it is the same 11px in all three cases below.
    """
    for width, height in ((720, 480), (500, 320), (1000, 800)):
        dialog = _dialog(qtbot)
        dialog.resize(width, height)
        qtbot.wait(20)
        window = dialog.rect()

        for seed in range(3):
            for particle in burst_confetti(dialog._copy_btn, rng=random.Random(seed)):
                for _pos, _opacity in _sweep(particle):
                    assert window.contains(particle.geometry()), (
                        f"at {width}x{height}, seed {seed}: a particle reached "
                        f"{particle.geometry()}, outside {window}"
                    )


def test_the_burst_fits_a_window_with_less_clearance_than_it_wants_to_use(qtbot):
    """The test above passes or fails on the host platform's button metrics.

    That is not a hypothetical, it is what happened. Its three dialog sizes all
    leave the same clearance under the copy button, and how much that is depends
    on how tall the platform's style draws a push button: 25px on macOS, 22px on
    Linux. A button one row shorter sits lower in a bottom-anchored row, which
    puts the burst's origin one row lower too. The fall used to be drawn from a
    fixed 8-20px range, which came to exactly the macOS clearance and one pixel
    more than the Linux one -- so the same seed passed on one platform and failed
    on the other, by a single pixel, for the whole of this feature's development.

    This asks the question the size loop cannot: the anchor is walked into every
    corner and edge of a small host, far tighter than any real dialog, so
    containment can only come from the arc being clamped to the host and not from
    the ranges happening to fit. The last row of placements is flush against the
    bottom, where the correct arc has no downward travel at all.
    """
    from PySide6.QtWidgets import QPushButton

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(160, 120)
    anchor = QPushButton("go", host)
    anchor.resize(24, 16)
    host.show()
    qtbot.wait(20)
    window = host.rect()

    # Every corner, every edge midpoint, and the centre -- the extremes flush
    # against the host's edges rather than merely near them.
    placements = [
        (x, y)
        for y in (0, 52, 104)
        for x in (0, 68, 136)
    ]
    for x, y in placements:
        anchor.move(x, y)
        qtbot.wait(5)
        for seed in range(4):
            for particle in burst_confetti(anchor, rng=random.Random(seed)):
                for _pos, _opacity in _sweep(particle):
                    assert window.contains(particle.geometry()), (
                        f"anchor at ({x}, {y}), seed {seed}: a particle reached "
                        f"{particle.geometry()}, outside {window}"
                    )


def test_a_host_too_small_for_a_particle_still_bursts_without_dividing_by_zero(qtbot):
    """The bottom of the clamp, which is a real arithmetic edge and not a mood.

    Clamping the rise and the fall to the room the host has means both can come
    out zero, and the fade's crossing point is `rise / (rise + fall)` -- so the
    degenerate host is a ZeroDivisionError unless it is named. `burst_confetti`
    is exported and takes any widget, so "a host smaller than a particle" is
    reachable rather than theoretical. Nothing moves and nothing is thrown out
    of bounds; the particles simply fade where they are.
    """
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(3, 3)
    host.show()
    qtbot.wait(20)

    particles = burst_confetti(host, rng=random.Random(0))

    assert len(particles) == PARTICLE_COUNT
    for particle in particles:
        for pos, _opacity in _sweep(particle):
            assert pos.x() == 0 and pos.y() == 0, (
                f"a particle moved to {pos} on a host with no room to move in"
            )


def test_a_particle_has_faded_out_before_it_falls_below_where_it_started(qtbot):
    """The fade has to finish on the part of the arc that is still on screen.

    This is the size-independent half, and the one that holds for an anchor this
    module knows nothing about: whatever clearance a caller's window leaves under
    its button, the particle was inside that window at the moment it was thrown,
    so any point at or above the height it started from is safe and anything
    below it may not be. The fade therefore has to reach zero at that crossing
    rather than at the end of the animation.

    The original schedule (a keyframe at 0.5 against the raw clock, with all of
    the fade deliberately on the way down) put the entire fade *after* the
    crossing, and particles were measured leaving the dialog at opacity 1.0 --
    an abrupt disappearance at an edge, not a fade.
    """
    dialog = _dialog(qtbot)

    worst = 0.0
    for seed in range(8):
        for particle in burst_confetti(dialog._copy_btn, rng=random.Random(seed)):
            start_y = particle.pos().y()
            for pos, opacity in _sweep(particle):
                if pos.y() > start_y:
                    worst = max(worst, opacity)

    assert worst < 0.2, (
        f"a particle was still at opacity {worst:.3f} below the height it was "
        f"thrown from, where the window may already have clipped it"
    )


def test_a_particle_does_not_swallow_a_click_meant_for_the_button(qtbot):
    """`WA_TransparentForMouseEvents` is load-bearing, and nothing else sees it.

    The burst passes back over the button that started it, so a particle that
    accepted mouse events would make the copy button briefly dead under the
    pointer. `qtbot.mouseClick` cannot catch that: it posts the event straight at
    the widget it is handed and never hit-tests, so the repeated-click test above
    would pass just as happily against particles that swallow every click. This
    asks Qt's own hit-test instead, with a particle parked over the button.
    """
    dialog = _dialog(qtbot)
    button = dialog._copy_btn
    centre = button.mapTo(dialog, button.rect().center())

    particle = ConfettiParticle("#e6194b", 8, dialog)
    particle.move(centre.x() - 4, centre.y() - 4)
    particle.show()
    particle.raise_()
    qtbot.wait(20)

    assert dialog.childAt(centre) is button

    # The control, so that the assertion above is known to be testing the
    # attribute rather than the stacking order: the same particle in the same
    # place does take the hit the moment the attribute is cleared.
    particle.setAttribute(Qt.WA_TransparentForMouseEvents, False)
    assert dialog.childAt(centre) is particle


def test_no_burst_when_there_is_no_clipboard(qtbot, monkeypatch):
    """Nothing was copied, so there is nothing to celebrate."""
    dialog = _dialog(qtbot)
    monkeypatch.setattr(errors, "QApplication", _NoClipboard)

    dialog._copyReport()

    assert _particles(dialog) == []


def test_the_copied_label_is_unchanged_on_both_paths(qtbot, monkeypatch):
    """The regression risk of touching this handler at all.

    The label was set on both the clipboard and the no-clipboard path before
    this change, and it still is. Pinned because the natural way to write the
    "only celebrate a real copy" guard is an early `return` on a null clipboard,
    which would silently take the label with it.
    """
    dialog = _dialog(qtbot)
    assert dialog._copy_btn.text() == "Copy report to clipboard"
    dialog._copyReport()
    assert dialog._copy_btn.text() == "Copied ✓"

    other = _dialog(qtbot)
    monkeypatch.setattr(errors, "QApplication", _NoClipboard)
    other._copyReport()
    assert other._copy_btn.text() == "Copied ✓"


def test_every_particle_is_deleted_once_its_animation_finishes(qtbot):
    """No leaked widgets. The burst owns its own cleanup."""
    dialog = _dialog(qtbot)
    dialog._copyReport()
    assert _particles(dialog)

    qtbot.wait(SETTLE_MS)

    assert _particles(dialog) == []


def test_repeated_clicks_neither_crash_nor_accumulate(qtbot):
    """Ten copies in a row, then nothing left behind.

    The clicks are real mouse clicks through the button rather than direct
    calls, so the wiring from `clicked` to the burst is covered once here.
    """
    dialog = _dialog(qtbot)

    for _ in range(10):
        qtbot.mouseClick(dialog._copy_btn, Qt.LeftButton)
        qtbot.wait(20)

    assert dialog._copy_btn.text() == "Copied ✓"
    # Mid-flight there are many; the ceiling is what a single click makes times
    # the clicks that can still be in the air, and the floor is that clicking
    # again does not stop the previous burst from ever being collected.
    qtbot.wait(SETTLE_MS)
    assert _particles(dialog) == []


def test_an_unparented_anchor_bursts_onto_itself(qtbot):
    """`burst_confetti` is exported, so it has to hold up away from the dialog.

    An un-parented, never-shown widget is its own window in Qt's model, so the
    burst is legal and lands on the anchor. Worth pinning because the coordinate
    mapping is the part that has already bitten once: `mapTo`'s argument must be
    an ancestor, the degenerate "ancestor is the widget itself" case is the one
    a caller hits first, and getting the direction wrong is a segfault in
    PySide6 6.5.2 rather than an exception a caller could survive.
    """
    from PySide6.QtWidgets import QPushButton

    orphan = QPushButton("nowhere")
    qtbot.addWidget(orphan)

    particles = burst_confetti(orphan, count=3)

    assert len(particles) == 3
    assert all(p.parent() is orphan for p in particles)


def test_a_seeded_burst_is_reproducible(qtbot):
    """The randomness is injectable, so a burst can be repeated exactly.

    Not a property the feature needs, but the seam is what makes the geometry
    debuggable at all: without it, a burst that goes wrong on one machine cannot
    be reproduced on another.
    """
    dialog = _dialog(qtbot)
    first = burst_confetti(dialog._copy_btn, count=4, rng=random.Random(7))
    second = burst_confetti(dialog._copy_btn, count=4, rng=random.Random(7))

    assert [p.size() for p in first] == [p.size() for p in second]
    assert [p.pos() for p in first] == [p.pos() for p in second]

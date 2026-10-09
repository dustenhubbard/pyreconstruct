import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QFontMetrics, QFont

from PyReconstruct.modules.datatypes.default_settings import (
    MAX_PINNED_UM,
    MIN_PINNED_UM,
    clampScaleBarThickness,
    validPinnedLength,
)
from PyReconstruct.modules.gui.utils import drawOutlinedText

from .buttons import MoveableButton

# How finely to tick a bar of each round length.
#
# Each entry is (mantissa, subdivisions) and repeats once per decade, so 2.0
# covers 0.2 µm, 2 µm, 20 µm and so on.  The subdivisions are chosen per entry
# so every tick label is round as well: 2 µm in 4 gives 0.5 µm ticks, where the
# historic fixed 5 would give 0.4 µm.  Where more than one divisor qualifies,
# the one nearest the historic 5 wins.  A micron-pinned bar can be any of these
# lengths, which is why the table is wider than the ladder below.
TICK_SUBDIVISIONS = (
    (1.0, 5),    # ticks every 0.2
    (1.5, 3),    # ticks every 0.5
    (2.0, 4),    # ticks every 0.5
    (2.5, 5),    # ticks every 0.5
    (3.0, 6),    # ticks every 0.5
    (4.0, 4),    # ticks every 1
    (5.0, 5),    # ticks every 1
    (6.0, 6),    # ticks every 1
    (7.0, 7),    # ticks every 1
    (8.0, 4),    # ticks every 2
    (9.0, 3),    # ticks every 3
    (10.0, 5),   # ticks every 2
)

# The ladder of lengths the screen-fraction bar is allowed to be.
#
# The bar is never drawn at the widget's full width: it is cut back to the
# longest "nice" length that still fits, so that the number printed under it is
# a round value a reader can trust on a figure.  The ladder is 1, 2, 5 per
# decade, the steps a map's scale bar takes.  Consecutive rungs are at most
# 2.5x apart, so the drawn bar always fills between 40 % and 100 % of its
# widget: as the zoom changes the bar's width follows it, and when the bar
# would outgrow the widget the label steps to the next rung down.
NICE_LENGTHS = tuple(
    rung for rung in TICK_SUBDIVISIONS if rung[0] in (1.0, 2.0, 5.0, 10.0)
)


def niceLength(max_len, rungs=None):
    """Return the longest ladder rung that fits within max_len.

        Params:
            max_len (float): the largest length, in real-world units, the bar
                             widget has room for
            rungs (tuple): the ladder, as (mantissa, subdivisions) pairs in
                           ascending order; defaults to NICE_LENGTHS, read at
                           call time so a test can swap the module's ladder
        Returns:
            (float, int): the bar's length in real-world units, and the number
                          of segments its ticks divide it into.  (0.0, 0) when
                          there is no room to draw, which is what a zero width
                          or a zero scale means.
    """
    if rungs is None:
        rungs = NICE_LENGTHS
    if not max_len > 0:  # zero width, zero scale, or NaN: nothing to draw
        return 0.0, 0

    decade = 10.0 ** math.floor(math.log10(max_len))
    mantissa = max_len / decade

    # the tolerance is what keeps a length that is exactly a rung on that rung:
    # 0.3 divided by its decade is 2.9999999999999996, and without the slack it
    # would fall back to 2.5 and leave a fifth of the widget empty
    length, subdivs = rungs[0][0] * decade, rungs[0][1]
    for m, s in rungs:
        if m <= mantissa + 1e-9:
            length, subdivs = m * decade, s

    return length, subdivs


# The shortest bar, in screen pixels, that is still worth drawing.
#
# Only the micron-pinned mode needs this.  A bar pinned to a fixed real-world
# length shrinks as the user zooms out, and below roughly this width it is
# narrower than the label printed over it, so the reader gets a caption with no
# measurable rule under it.  40 px is a little wider than "5 µm" set in the
# 12 pt bold Courier the label uses.
MIN_PINNED_PIXELS = 40

# How far a bar's width may fall outside `min_pix` to `max_pix`, as a fraction
# of the bound, and still count as inside.
#
# A length typed from the range the dialog shows can land a hair outside it in
# floating point: 0.011 µm at 0.000275 µm/px is 39.99999999999999 px, not 40.
# `drawableLengths` and `pinnedLength` both test widths through `tooNarrow`
# and `tooWide`, so every length the range offers draws at that length.
PIXEL_TOLERANCE = 1e-9


def tooNarrow(pixels, min_pix):
    """Whether a bar `pixels` wide is shorter than `min_pix`."""
    return pixels < min_pix * (1 - PIXEL_TOLERANCE)


def tooWide(pixels, max_pix):
    """Whether a bar `pixels` wide is longer than `max_pix`."""
    return pixels > max_pix * (1 + PIXEL_TOLERANCE)


def pinnedLength(micron_length, scale, max_pix, min_pix=MIN_PINNED_PIXELS):
    """Return the length a micron-pinned bar should actually draw.

    In micron-pinned mode the user picks a length in real-world units and the
    bar's pixel width follows the zoom, which is the inverse of what
    `niceLength` does.  The whole point of the mode is that the number under the
    bar does not move, so this returns the user's own length untouched wherever
    it can be drawn.

    It cannot always be drawn.  Zoomed far out, `micron_length / scale` falls to
    a handful of pixels; zoomed far in, it runs off the side of the field.  A
    scale bar whose drawn length does not match its printed label is worse than
    useless on a figure, so the pixel width is never clamped on its own: when
    the requested length will not fit the drawable range, the *length itself*
    moves, by whole decades, and the label moves with it.  The mantissa the user
    chose is invariant -- 5 µm becomes 0.5 µm or 50 µm, never 4 µm or 6 µm -- so
    the bar still reads as the number they asked for, and the drawn rule always
    measures exactly what the label says.

    This deliberately does not reuse `NICE_LENGTHS`.  That ladder exists to snap
    a screen-fraction bar down to a round number, which is a different job: it
    would replace the user's chosen length rather than rescale it.  What the two
    modes share is the cap: `max_pix` is the "Scale bar size" share of the
    field, the same width a screen-fraction bar is held inside.

        Params:
            micron_length (float): the length the user pinned the bar to, in
                                   real-world units
            scale (float): real-world units per screen pixel (the current zoom)
            max_pix (int): the widest the bar is allowed to be drawn, in pixels
                           -- the scale bar size option's share of the field
            min_pix (int): the narrowest bar still worth drawing, in pixels
        Returns:
            (float, int): the bar's length in real-world units, and that length
                          in screen pixels.  (0.0, 0) when there is nothing to
                          draw, matching `niceLength`.
    """
    # validPinnedLength rather than `micron_length > 0`: inf passes the latter
    # and then reaches math.log10(0.0) below.  See that function.
    if not (validPinnedLength(micron_length) and scale > 0 and max_pix > 0):
        return 0.0, 0

    def pixels(exponent):
        return micron_length * 10.0 ** exponent / scale

    # first guess: the decade shift that lands inside the range, read straight
    # off the logarithm.  The epsilons keep a length that sits exactly on a
    # boundary on its own decade rather than one step past it, the same job the
    # tolerance does in niceLength.
    exponent = 0
    if tooWide(pixels(0), max_pix):
        exponent = math.floor(math.log10(max_pix * scale / micron_length) + 1e-9)
    elif tooNarrow(pixels(0), min_pix):
        exponent = math.ceil(math.log10(min_pix * scale / micron_length) - 1e-9)

    # then correct it by measurement, because the guess is a float computation
    # and the invariant below is the thing that actually has to hold.  Both
    # loops are bounded: each step multiplies or divides the width by ten.
    steps = 0
    while tooWide(pixels(exponent), max_pix) and steps < 400:
        exponent -= 1
        steps += 1
    # growing is only allowed while it still fits; on a field too narrow to hold
    # one whole decade there may be no exponent that satisfies both bounds, and
    # fitting wins -- a bar that overruns the field is clipped and lies about its
    # length, a bar that is too short is merely hard to read.
    while (tooNarrow(pixels(exponent), min_pix)
           and not tooWide(pixels(exponent + 1), max_pix) and steps < 400):
        exponent += 1
        steps += 1

    real_len = micron_length * 10.0 ** exponent
    pix_len = int(real_len / scale)
    if pix_len <= 0:
        return 0.0, 0
    return real_len, pix_len


def drawableLengths(scale, max_pix, min_pix=MIN_PINNED_PIXELS):
    """The shortest and longest lengths `pinnedLength` draws exactly.

    Exactly means unshifted: the bar is the length asked for, so its label is
    that length too.  That takes two things at once -- between `min_pix` and
    `max_pix` wide at this zoom, and a length `validPinnedLength` accepts --
    so the range is the overlap of the two.  Both ends are rounded inward to
    three figures, so either can be typed back and still fall inside.  Inside
    means what `pinnedLength` takes it to mean: `tooNarrow` and `tooWide`,
    whose tolerance the rounding starts from.

        Params:
            scale (float): real-world units per screen pixel
            max_pix (int): the widest the bar may be drawn, in pixels
            min_pix (int): the narrowest bar still worth drawing, in pixels
        Returns:
            (float, float): the range in real-world units.  The first is
                            larger than the second when there is no length
                            to draw: a field narrower than `min_pix`, or a
                            zoom so far out or in that the field holds no
                            length a bar may be.
    """
    if not (scale > 0 and max_pix > 0):
        return math.inf, 0.0

    def sig(value, up):
        exponent = math.floor(math.log10(value)) - 2
        digits = (math.ceil if up else math.floor)(value / 10.0 ** exponent)
        # through text, so 715e-3 is the same float as a typed 0.715
        return float(f"{digits}e{exponent}")

    shortest = min_pix * (1 - PIXEL_TOLERANCE) * scale
    longest = max_pix * (1 + PIXEL_TOLERANCE) * scale
    return (max(sig(shortest, True), MIN_PINNED_UM),
            min(sig(longest, False), MAX_PINNED_UM))


def pinnedSubdivisions(real_len, rungs=None):
    """How finely to tick a micron-pinned bar of this length.

    The screen-fraction bar always lands on a `NICE_LENGTHS` rung, so it always
    has a subdivision count that cuts it into round numbers.  A pinned bar is
    whatever the user typed, so it is looked up in the wider `TICK_SUBDIVISIONS`
    table, and it may not be there: 3.7 µm has no division into two to seven
    parts that prints roundly.  Rather than print ticks labelled 0.74 and 1.48,
    a length that is not in the table gets no interior ticks at all -- 1, which
    `paintEvent`'s `range(1, subdivs)` draws as none.

        Params:
            real_len (float): the bar's length in real-world units
            rungs (tuple): the table, as (mantissa, subdivisions) pairs;
                           defaults to TICK_SUBDIVISIONS, read at call time
        Returns:
            int: the number of segments to cut the bar into
    """
    if rungs is None:
        rungs = TICK_SUBDIVISIONS
    if not real_len > 0:
        return 1

    decade = 10.0 ** math.floor(math.log10(real_len))
    mantissa = real_len / decade
    for m, s in rungs:
        if abs(m - mantissa) < 1e-9:
            return s
    return 1


def formatLength(value):
    """Render a length the way a figure caption would: no trailing zeros.

    The bar's own label and its tick labels both go through here so that one
    length always prints one way.  Before, the label was built with `str()` on
    the arithmetic's result, so the same 10 µm bar printed "10 µm" or "10.0 µm"
    depending on which side of a decade the zoom happened to be on, and every
    tick label carried a trailing ".0".
    """
    if not value > 0:
        return "0"
    text = f"{value:.10g}"
    if "e" in text or "E" in text:  # sub-ångström lengths, in principle
        text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


# The widget is stacked top to bottom: the label, the bar, the tick marks, the
# tick labels.  Only the bar's own thickness is an option; the rest is the room
# the text needs, in pixels, and is left out when its text or ticks are off so
# that no empty grab area sits over the field.
LABEL_ROOM = 22       # the 12 pt bold label, centered in this band
TICK_LENGTH = 5       # how far a tick mark hangs below the bar
TICK_LABEL_ROOM = 18  # the small tick labels, centered in this band
LABEL_SIZE = 12       # the label's font size
TICK_LABEL_SIZE = 10  # the tick labels' font size


def outlinedFont(size):
    """The font `drawOutlinedText` draws in for a painter font of pixel size
    `size`: it reads the pixel size back as a point size.  Text is measured in
    this, so a width worked out here is the width that is drawn."""
    return QFont("Courier New", size, QFont.Bold)


class ScaleBar(MoveableButton):

    def __init__(self, parent, manager, length, thickness, scale,
                 micron_length=None, max_pixel_length=None):
        """Create the scale bar.

            Params:
                parent (QWidget): the parent of the scale bar
                manager (QMainWindow): the manager of the scale bar
                length (int): the max pixel length of the scale bar
                thickness (int): the bar's own thickness in pixels; the widget
                                 is taller by the room its text needs
                scale (float): the number of real-world units per pixel
                micron_length (float): the real-world length to pin the bar to,
                                       or None (the default) for the historic
                                       screen-fraction sizing, where `length` is
                                       the room the bar may fill and the printed
                                       figure follows the zoom
                max_pixel_length (int): how wide the bar may grow when pinned;
                                        defaults to `length`, the same cap
                                        the screen-fraction bar has
        """
        super().__init__(parent, manager, "sb")
        self.scale = scale
        self.micron_length = micron_length
        self.max_pixel_length = length if max_pixel_length is None else max_pixel_length
        # a length set from the bar's right-click menu, and the room it
        # may grow into; never stored (MousePalette.reset carries it over a
        # rebuild on the same series)
        self.override_length = None
        self.override_room = 0
        self.thickness = clampScaleBarThickness(thickness)
        self.resize(length, self._layout()[2])
        self._fitPinned()

    def _layout(self):
        """Where the bar and its ticks sit: (bar top, tick label top, height)."""
        series = self.manager.series
        draw_text = series.getOption("show_scale_bar_text")
        draw_ticks = series.getOption("show_scale_bar_ticks")
        bar_top = LABEL_ROOM if draw_text else 1
        tick_label_top = bar_top + self.thickness + TICK_LENGTH
        height = tick_label_top + 1
        if draw_ticks and draw_text:
            height = tick_label_top + TICK_LABEL_ROOM
        elif not draw_ticks:
            height = bar_top + self.thickness + 1
        return bar_top, tick_label_top, height

    def setThickness(self, thickness):
        """Change the bar's thickness; the widget's height follows it."""
        self.thickness = clampScaleBarThickness(thickness)
        height = self._layout()[2]
        if height != self.height():
            self.resize(self.width(), height)
        self.update()

    def setScale(self, scale):
        self.scale = scale
        self._fitPinned()
        self.update()

    def setMaxPixelLength(self, max_pixel_length):
        """Say how much room the scale bar size option gives the bar.

        A screen-fraction widget is that room, so it takes the new width; a
        pinned widget is the size of its bar, which `_fitPinned` works out.
        """
        if max_pixel_length == self.max_pixel_length:
            return
        self.max_pixel_length = max_pixel_length
        if not self._pinned():
            self.resize(max_pixel_length, self.height())
        self._fitPinned()
        self.update()

    def setOverride(self, length, room=0):
        """Draw `length` µm whatever the mode, until called with None.

        Someone exporting a figure may want a length the automatic sizing
        would not pick, so `room` is the field width rather than the scale bar
        size: the user asked for this length, so the size option does not cap
        it. Out of that room the bar steps a decade, the same as a pinned bar,
        so its label still matches what it measures.
        """
        self.override_length = length
        self.override_room = room
        if not self._pinned():
            self.resize(self.max_pixel_length, self.height())
        self._fitPinned()
        self.update()

    def _pinned(self):
        """The length the bar is held to and the widest it may grow, or None
        for the screen-fraction bar."""
        if self.override_length:
            return self.override_length, self.override_room
        if self.micron_length:
            return self.micron_length, self.max_pixel_length
        return None

    def pinnedRender(self):
        """The pinned bar's length and tick count at the current zoom."""
        micron_length, room = self._pinned()
        real_len, pix_len = pinnedLength(micron_length, self.scale, room)
        return real_len, pix_len, pinnedSubdivisions(real_len)

    def currentLength(self):
        """The length the bar draws at the current zoom, and its tick count."""
        if self._pinned():
            # a fixed real-world length: the pixels follow the zoom
            real_len, _pix_len, subdivs = self.pinnedRender()
        else:
            # the longest nice length that fits the widget, and how finely to tick it
            real_len, subdivs = niceLength(self.width() * self.scale)
        return real_len, subdivs

    def _fitPinned(self):
        """Resize the widget to the pinned bar, so the paint is never clipped.

        In screen-fraction mode the widget's width is the room the bar may fill
        and never moves.  Pinned, the bar *is* its width -- the widget is also
        the drag handle, so leaving it at full field width would put an
        invisible grab target over the field.  The resize happens here rather
        than in `paintEvent`, which must not change geometry.
        """
        if not self._pinned():
            return
        real_len, pix_len, _subdivs = self.pinnedRender()
        # never narrower than the label, which would be cut off at the sides
        width = max(pix_len, self.labelWidth(real_len) + 2)
        if pix_len > 0 and width != self.width():
            self.resize(width, self.height())

    def labelWidth(self, real_len):
        """How wide the label over a bar of `real_len` µm is drawn, or 0."""
        if not self.manager.series.getOption("show_scale_bar_text"):
            return 0
        metrics = QFontMetrics(outlinedFont(LABEL_SIZE))
        return metrics.horizontalAdvance(formatLength(real_len) + " µm")

    def paintEvent(self, event):
        real_len, subdivs = self.currentLength()
        if real_len <= 0:
            return
        pix_len = int(real_len / self.scale)

        # check text and tick preferences
        draw_text = self.manager.series.getOption("show_scale_bar_text")
        draw_ticks = self.manager.series.getOption("show_scale_bar_ticks")
        bar_top, tick_label_top, _height = self._layout()

        white, black = QColor(255, 255, 255), QColor(0, 0, 0)
        painter = QPainter(self)
        # no pen: the outline is the white rectangle's own edge, so the bar
        # looks the same whatever the theme's text color is
        painter.setPen(Qt.NoPen)

        # draw the scale bar: a black fill inside a 1 px white edge, which
        # reads on a light image and a dark one alike
        r_x = 0
        r_y = bar_top
        r_w = pix_len
        r_h = self.thickness
        painter.setBrush(white)
        painter.drawRect(r_x, r_y, r_w, r_h)
        painter.setBrush(black)
        painter.drawRect(r_x + 1, r_y + 1, r_w - 2, r_h - 2)

        # draw text
        if draw_text:
            font = QFont("Courier New")
            font.setPixelSize(LABEL_SIZE)
            font.setBold(True)
            l_text = formatLength(real_len) + " µm"
            painter.setFont(font)
            # over the bar's middle, unless the bar is shorter than its label
            drawCenteredText(
                painter,
                max(r_x + r_w/2, self.labelWidth(real_len) / 2 + 1),
                bar_top / 2,
                l_text,
                outlined=True
            )

        # draw ticks if requested: each hangs below the bar, black with a
        # white edge like the bar, and its label is outlined like the main one
        if draw_ticks:
            small_font = QFont("Courier New")  # used for ticks
            small_font.setPixelSize(TICK_LABEL_SIZE)
            small_font.setBold(True)
            # on a short bar the tick labels would run into each other, so
            # only every `step`-th tick is labelled, as few as keep them apart
            step = 1
            if draw_text and subdivs > 1:
                metrics = QFontMetrics(outlinedFont(TICK_LABEL_SIZE))
                widest = max(
                    metrics.horizontalAdvance(formatLength(real_len * i/subdivs))
                    for i in range(1, subdivs)
                )
                step = max(1, math.ceil((widest + 6) / (r_w / subdivs)))
            for i in range(1, subdivs):
                t_x = int(r_x + r_w/subdivs * i)
                painter.setBrush(white)
                painter.drawRect(t_x - 1, r_y + r_h - 1, 3, TICK_LENGTH + 1)
                painter.setBrush(black)
                painter.drawRect(t_x, r_y + r_h - 1, 1, TICK_LENGTH)
                if draw_text and i % step == 0:
                    painter.setFont(small_font)
                    t_text = formatLength(real_len * i/subdivs)
                    drawCenteredText(
                        painter,
                        t_x,
                        tick_label_top + TICK_LABEL_ROOM / 2,
                        t_text,
                        outlined=True
                    )

        painter.end()

def drawCenteredText(painter, x, y, text, outlined=False):
    font = painter.font()
    if outlined and font.pixelSize() > 0:
        font = outlinedFont(font.pixelSize())  # what drawOutlinedText draws in
    font_metrics = QFontMetrics(font)
    text_rect = font_metrics.boundingRect(text)
    adjusted_x = x - text_rect.width() / 2
    adjusted_y = y + text_rect.height() / 2
    if outlined:
        drawOutlinedText(
            painter,
            adjusted_x,
            adjusted_y,
            text
        )
    else:
        painter.drawText(adjusted_x, adjusted_y, text)


